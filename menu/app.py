"""Single-entry web application for the Drishti Drive menu and its tools.

Change the paths in ``FEATURE_PATHS`` when a feature is moved.  The menu,
ANPR, and Tracking & OCR pages are then served by this one application.
"""

from datetime import date, datetime
from functools import lru_cache
import csv
import importlib.util
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from menu.subscription import (
    is_subscription_active,
    require_tracking_subscription,
    router as subscription_router,
)

# Central feature-path configuration. Update only these entries if folders move.
FEATURE_PATHS = {
    "menu_frontend": PROJECT_DIR / "menu" / "menu_frontend",
    "anpr_backend": PROJECT_DIR / "menu" / "ANPR" / "ANPR_backend" / "main.py",
    "anpr_frontend": PROJECT_DIR / "menu" / "ANPR" / "ANPR_frontend",
    "traffic_backend": PROJECT_DIR / "Traffic" / "traffic_backend" / "traffic_backend.py",
    "traffic_frontend": PROJECT_DIR / "Traffic" / "traffic_frontend",
    "tracking_frontend": PROJECT_DIR / "menu" / "tracking and ocr",
    "navbar": PROJECT_DIR / "menu" / "navbar",
    "shared_assets": PROJECT_DIR / "menu",
    "cameras": PROJECT_DIR / "cameras",
    "owner_details": PROJECT_DIR / "menu" / "owner_details.csv",
    "vehicle_data": PROJECT_DIR / "menu" / "ANPR" / "vehicle_data.csv",
}
MENU_FRONTEND_DIR = FEATURE_PATHS["menu_frontend"]
TRACKING_DIR = FEATURE_PATHS["tracking_frontend"]
CAMERAS_DIR = FEATURE_PATHS["cameras"]
OWNER_DETAILS_FILES = (
    FEATURE_PATHS["owner_details"],
    FEATURE_PATHS["vehicle_data"],
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Drishti Drive")
app.include_router(subscription_router)


@app.middleware("http")
async def require_subscription_for_traffic(request: Request, call_next):
    if request.url.path == "/traffic" or request.url.path.startswith("/traffic/"):
        if not is_subscription_active(request):
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse(
                    "/tracking/?next=%2Ftraffic%2F",
                    status_code=303,
                )
            return JSONResponse(
                status_code=402,
                content={
                    "detail": "An active ₹99/month subscription is required for Tracking / OCR and Traffic.",
                    "subscription_url": "/tracking/?next=%2Ftraffic%2F",
                },
            )
    return await call_next(request)


def load_anpr_app():
    """Load the existing ANPR application without duplicating its code."""
    backend_file = FEATURE_PATHS["anpr_backend"]
    if not backend_file.is_file():
        raise RuntimeError(f"ANPR backend was not found: {backend_file}")
    anpr_frontend = FEATURE_PATHS["anpr_frontend"]
    if not anpr_frontend.is_dir():
        raise RuntimeError(f"ANPR frontend was not found: {anpr_frontend}")

    # The mounted ANPR application reads this setting, keeping all moved-folder
    # configuration in FEATURE_PATHS above.
    os.environ["DRISHTI_ANPR_FRONTEND_DIR"] = str(anpr_frontend)
    os.environ["DRISHTI_OWNER_DETAILS_PATH"] = str(FEATURE_PATHS["owner_details"])

    spec = importlib.util.spec_from_file_location("drishti_anpr", backend_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load ANPR backend: {backend_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.app


def load_traffic_app():
    """Load the existing Traffic application under the menu server."""
    backend_file = FEATURE_PATHS["traffic_backend"]
    frontend_dir = FEATURE_PATHS["traffic_frontend"]
    if not backend_file.is_file() or not frontend_dir.is_dir():
        raise RuntimeError("Traffic frontend or backend was not found.")

    spec = importlib.util.spec_from_file_location("drishti_traffic", backend_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Traffic backend: {backend_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.app


def normalize_plate(plate: str) -> str:
    return "".join(character for character in plate.upper() if character.isalnum())


def load_vehicle_owner(plate: str) -> dict | None:
    owner_data_file = next((path for path in OWNER_DETAILS_FILES if path.exists()), None)
    if owner_data_file is None:
        return None
    with owner_data_file.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            normalized_row = {str(key).strip(" `"): value for key, value in row.items()}
            if normalize_plate(normalized_row.get("plate_number", "")) == plate:
                return normalized_row
    return None


def load_sightings(plate: str, on_date: str | None = None) -> list[dict]:
    sightings = []
    for camera_file in sorted(CAMERAS_DIR.glob("*.csv")):
        with camera_file.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                if normalize_plate(row.get("plate_number", "")) != plate:
                    continue
                if on_date and row.get("date") != on_date:
                    continue
                timestamp = datetime.fromisoformat(f"{row['date']}T{row['time']}")
                sightings.append({**row, "timestamp": timestamp.isoformat()})
    return sorted(sightings, key=lambda row: row["timestamp"])


@app.get("/api/vehicles/{plate}", dependencies=[Depends(require_tracking_subscription)])
async def get_vehicle(plate: str, on_date: str | None = None):
    normalized_plate = normalize_plate(plate)
    if on_date:
        requested_date = on_date
    else:
        # A trajectory demo often contains historical data. Select the date
        # with the most sightings rather than returning no result on today's date.
        sightings_by_date = {}
        for camera_file in CAMERAS_DIR.glob("*.csv"):
            with camera_file.open(encoding="utf-8", newline="") as file:
                for row in csv.DictReader(file):
                    if normalize_plate(row.get("plate_number", "")) == normalized_plate:
                        sightings_by_date[row["date"]] = sightings_by_date.get(row["date"], 0) + 1
        requested_date = max(sightings_by_date, key=sightings_by_date.get) if sightings_by_date else date.today().isoformat()
    owner = load_vehicle_owner(normalized_plate)
    sightings = load_sightings(normalized_plate, requested_date)
    if not owner and not sightings:
        raise HTTPException(status_code=404, detail="Vehicle was not found in the camera records.")
    if not sightings:
        raise HTTPException(status_code=404, detail=f"No camera sightings found for {requested_date}.")
    return {
        "plate_number": owner["plate_number"] if owner else plate.upper(),
        "owner": owner or {},
        "date": requested_date,
        "default_start": sightings[0]["timestamp"],
        "default_end": sightings[-1]["timestamp"],
        "start_location": sightings[0],
        "end_location": sightings[-1],
        "sightings": sightings,
    }


@app.get(
    "/api/vehicles/{plate}/route",
    dependencies=[Depends(require_tracking_subscription)],
)
async def get_vehicle_route(plate: str, start: str, end: str):
    try:
        start_time, end_time = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Start and end must be valid date-time values.") from error
    if end_time < start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    sightings = load_sightings(normalize_plate(plate))
    route = [
        row for row in sightings
        if start_time <= datetime.fromisoformat(row["timestamp"]) <= end_time
    ]
    if not route:
        raise HTTPException(status_code=404, detail="No vehicle sightings exist in the selected time range.")
    return {"plate_number": plate.upper(), "start": route[0], "end": route[-1], "points": route}


@lru_cache(maxsize=1)
def get_ocr_engine():
    """Load PaddleOCR only when an image is submitted."""
    ocr_file = TRACKING_DIR / "iamge_to_number.py"
    spec = importlib.util.spec_from_file_location("drishti_tracking_ocr", ocr_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"OCR module was not found: {ocr_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DynamicANPR()


@app.post("/api/recognize-plate", dependencies=[Depends(require_tracking_subscription)])
async def recognize_plate(image: UploadFile = File(...)):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Please upload an image file.")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 10 MB or smaller.")

    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Unable to read the uploaded image.")
    result = await run_in_threadpool(get_ocr_engine().recognize, frame)
    return {"plate": result["plate"], "detected": result["status"]}


@app.get("/", include_in_schema=False)
async def serve_menu():
    return FileResponse(MENU_FRONTEND_DIR / "index.html")


# Register static sites last so API routes take precedence.
app.mount("/tracking", StaticFiles(directory=TRACKING_DIR, html=True), name="tracking")
app.mount("/anpr", load_anpr_app(), name="anpr")
app.mount("/traffic", load_traffic_app(), name="traffic")
app.mount("/assets", StaticFiles(directory=FEATURE_PATHS["shared_assets"]), name="shared-assets")
app.mount("/navbar", StaticFiles(directory=FEATURE_PATHS["navbar"]), name="navbar-assets")
# This serves the landing page's local stylesheet, logo, and any future assets.
app.mount("/", StaticFiles(directory=MENU_FRONTEND_DIR, html=True), name="menu-assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
