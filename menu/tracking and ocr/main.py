from functools import lru_cache
import logging
from pathlib import Path
import csv
from datetime import date, datetime

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent.parent
GIS_FRONTEND_DIR = BASE_DIR
CAMERAS_DIR = PROJECT_DIR / "cameras"
# Prefer the dedicated owner file when supplied; retain the original dataset as
# a fallback so existing installations continue to work without migration.
OWNER_DETAILS_FILES = (
    BASE_DIR / "owner_details.csv",
    BASE_DIR / "owner_detils.csv",
    PROJECT_DIR / "menu" / "owner_details.csv",
    PROJECT_DIR / "menu" / "ANPR" / "vehicle_data.csv",
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024

app = FastAPI()
logger = logging.getLogger(__name__)


def normalize_plate(plate: str) -> str:
    return "".join(character for character in plate.upper() if character.isalnum())


def load_vehicle_owner(plate: str) -> dict | None:
    owner_data_file = next((file for file in OWNER_DETAILS_FILES if file.exists()), None)
    if owner_data_file is None:
        return None
    with owner_data_file.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if normalize_plate(row["plate_number"]) == plate:
                return row
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


@app.get("/api/vehicles/{plate}")
async def get_vehicle(plate: str, on_date: str | None = None):
    normalized_plate = normalize_plate(plate)
    if on_date:
        requested_date = on_date
    else:
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


@app.get("/api/vehicles/{plate}/route")
async def get_vehicle_route(plate: str, start: str, end: str):
    normalized_plate = normalize_plate(plate)
    try:
        start_time, end_time = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Start and end must be valid date-time values.") from error
    if end_time < start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    sightings = load_sightings(normalized_plate)
    route = [
        row for row in sightings
        if start_time <= datetime.fromisoformat(row["timestamp"]) <= end_time
    ]
    if not route:
        raise HTTPException(status_code=404, detail="No vehicle sightings exist in the selected time range.")
    return {"plate_number": plate.upper(), "start": route[0], "end": route[-1], "points": route}


@lru_cache(maxsize=1)
def get_ocr_engine():
    """Load PaddleOCR only when the first image is uploaded."""
    from gis_frontend.iamge_to_number import DynamicANPR
    return DynamicANPR()


@app.on_event("startup")
async def warm_ocr_engine():
    """Load OCR before the first upload so the UI stays responsive."""
    try:
        await run_in_threadpool(get_ocr_engine)
        logger.info("OCR engine is ready.")
    except Exception:
        logger.exception("OCR engine could not be initialized.")


@app.post("/api/recognize-plate")
async def recognize_plate(image: UploadFile = File(...)):
    """Recognize a vehicle plate from an uploaded image without saving it."""
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

    try:
        result = await run_in_threadpool(get_ocr_engine().recognize, frame)
    except Exception as error:
        logger.exception("Plate recognition failed.")
        raise HTTPException(
            status_code=500,
            detail="OCR processing failed. Check that PaddlePaddle 2.6.2 is installed.",
        ) from error

    return {"plate": result["plate"], "detected": result["status"]}


@app.get("/video2.mp4", include_in_schema=False)
async def get_video():
    video_path = BASE_DIR / "video2.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path)


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(GIS_FRONTEND_DIR / "index.html")


# Registered last so API routes take precedence over static-file matching.
app.mount("/", StaticFiles(directory=GIS_FRONTEND_DIR, html=True), name="gis_frontend")
