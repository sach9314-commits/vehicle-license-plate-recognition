import os
import random
import re
from datetime import datetime
import cv2
import numpy as np
import pandas as pd
import torch

# Fix for PyTorch 2.6+ loading issue
_orig_torch_load = torch.load
def _patched_torch_load(f, *args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_torch_load(f, *args, **kwargs)
torch.load = _patched_torch_load

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from ultralytics import YOLO

app = FastAPI()


def _is_client_disconnect(error):
    error_name = type(error).__name__
    if error_name in {"ClientDisconnected", "ClientDisconnect", "CancelledError"}:
        return True
    nested_errors = getattr(error, "exceptions", None)
    return bool(nested_errors) and all(_is_client_disconnect(item) for item in nested_errors)


class ClientSafeStreamingResponse(StreamingResponse):
    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        except BaseException as error:
            if not _is_client_disconnect(error):
                raise

# --- Absolute Path Configuration ---
# Current directory: ANPR/ANPR_backend/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Project root directory: ANPR/
ROOT_DIR = os.path.dirname(CURRENT_DIR)

# ``menu/app.py`` supplies this path when ANPR is mounted in the main site.
# The fallback also allows this backend to be run by itself.
FRONTEND_DIR = os.environ.get(
    "DRISHTI_ANPR_FRONTEND_DIR",
    os.path.join(ROOT_DIR, "ANPR_frontend"),
)
VIDEO_DIR = os.path.join(ROOT_DIR, "video_footage")
CSV_PATH = os.path.join(ROOT_DIR, "vehicle_data.csv")
MODEL_PATH = os.environ.get(
    "DRISHTI_YOLO_MODEL",
    next(
        (
            path
            for path in (
                os.path.join(CURRENT_DIR, "yolov8n.pt"),
                os.path.join(ROOT_DIR, "yolov8n.pt"),
                os.path.join(os.path.dirname(os.path.dirname(ROOT_DIR)), "yolov8n.pt"),
            )
            if os.path.exists(path)
        ),
        "yolov8n.pt",
    ),
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
templates = Jinja2Templates(directory=FRONTEND_DIR)

model = YOLO(MODEL_PATH)
PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")


def verify_and_get_details(plate_number: str):
    plate_upper = plate_number.upper().strip()

    is_valid_format = bool(PLATE_REGEX.match(plate_upper))
    format_msg = (
        "Valid Standard Format" if is_valid_format else "❌ Invalid Plate Format"
    )
    format_class = (
        "text-emerald-400 bg-emerald-950/60 border-emerald-800/60"
        if is_valid_format
        else "text-red-400 bg-red-950/60 border-red-800/60"
    )

    owner_data = {}
    db_status = "Unregistered / Not Found"

    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        df.columns = df.columns.str.strip()
        df["plate_number"] = df["plate_number"].astype(str).str.strip().str.upper()
        match = df[df["plate_number"] == plate_upper]
        if not match.empty:
            db_status = "Verified in DB (Parivahan)"
            row = match.iloc[0].to_dict()
            owner_data = {
                "plate_number": row.get("plate_number"),
                "owner": row.get("owner_name"),
                "phone": row.get("phone_number"),
                "email": row.get("email"),
                "address": row.get("address"),
                "status": row.get("status", "RC Active"),
                "rc_expiry": str(row.get("rc_expiry", "2028-01-01")),
                "puc_expiry": str(row.get("puc_expiry", "2027-01-01")),
            }

    if not owner_data:
        owner_data = {
            "plate_number": plate_upper,
            "owner": "Unknown / Unregistered Vehicle",
            "phone": "N/A",
            "email": "N/A",
            "address": "No matching record found in state registry database.",
            "status": "Alert / Unverified",
            "rc_expiry": "N/A",
            "puc_expiry": "N/A",
        }

    compliance_alert = None
    rc_status = owner_data.get("status", "RC Active")

    if not is_valid_format:
        compliance_alert = (
            f"WRONG FORMAT: Plate {plate_upper} violates standard Indian numbering!"
        )
    elif rc_status == "RC Expired":
        compliance_alert = f"RC EXPIRED ALERT: Vehicle {plate_upper} ({owner_data['owner']}) registration has expired!"

    return (
        format_msg,
        format_class,
        db_status,
        owner_data,
        compliance_alert,
    )


def generate_frames(video_path: str):
    if not os.path.exists(video_path):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            blank,
            "Video Not Found",
            (180, 240),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            2,
        )
        _, buffer = cv2.imencode(".jpg", blank)
        while True:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            )
        return

    cap = cv2.VideoCapture(video_path)
    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            results = model(frame, conf=0.5, verbose=False)
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame,
                        f"AI Target {conf:.2f}",
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )

            _, buffer = cv2.imencode(".jpg", frame)
            frame_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
    finally:
        cap.release()


@app.get("/video_feed/{cam_id}")
async def video_feed(cam_id: int):
    video_file = os.path.join(VIDEO_DIR, f"video{cam_id}.mp4")
    if not os.path.exists(video_file):
        video_file = os.path.join(VIDEO_DIR, "video1.mp4")
    return ClientSafeStreamingResponse(
        generate_frames(video_file),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/latest-detection")
async def latest_detection():
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        sample_plates = df["plate_number"].dropna().tolist()
    else:
        sample_plates = ["TN21AT0480", "HR26CK8571", "MH20BY3665", "CH01BL5800"]

    selected_plate = random.choice(sample_plates)
    cameras = [
        "CAM-01 (Vishesh Tyagi Chowk)",
        "CAM-02 (Maharishi Ashram Chowk)",
        "CAM-03 (Bhangel)",
        "CAM-04 (Metro Sec 76)",
    ]
    cam_name = random.choice(cameras)

    format_msg, format_class, db_status, owner_data, compliance_alert = (
        verify_and_get_details(selected_plate)
    )
    current_time = datetime.now().strftime("%I:%M:%S %p")

    return {
        "success": True,
        "time": current_time,
        "camera": cam_name,
        "plate": selected_plate,
        "status": "Processed",
        "owner_details": owner_data,
        "speed_status": f"Normal ({random.randint(40, 65)} km/h)",
        "format_msg": format_msg,
        "format_class": format_class,
        "db_status": db_status,
        "compliance_alert": compliance_alert,
    }


@app.get("/", response_class=HTMLResponse)
async def live_surveillance_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"current_page": "live"}
    )
