import os
import random
import re
import csv
import threading
from datetime import datetime, timezone
import cv2
import numpy as np
import pandas as pd
import torch

# PyTorch 2.6+ safe weight loader patch
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

# --- Absolute Path Configuration based on Directory Structure ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))               # cameras/Traffic/traffic_backend
TRAFFIC_DIR = os.path.dirname(CURRENT_DIR)                             # cameras/Traffic
CAMERAS_DIR = os.path.dirname(TRAFFIC_DIR)                             # cameras

# Paths mapped to project structure
FRONTEND_DIR = os.path.join(TRAFFIC_DIR, "traffic_frontend")
VIDEO_DIR = os.path.join(CAMERAS_DIR, "menu", "ANPR", "video_footage")
CSV_PATH = os.path.join(CAMERAS_DIR, "menu", "ANPR", "vehicle_data.csv")
MODEL_PATH = os.path.join(TRAFFIC_DIR, "yolov8n.pt")
TRAFFIC_CSV_DIR = os.path.join(TRAFFIC_DIR, "traffic_csv")

# Fallback to root model if not present in Traffic/
if not os.path.exists(MODEL_PATH):
    MODEL_PATH = os.path.join(CAMERAS_DIR, "yolov8n.pt")

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/media", StaticFiles(directory=VIDEO_DIR), name="media")
templates = Jinja2Templates(directory=FRONTEND_DIR)

model = YOLO(MODEL_PATH)
PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

# Live per-camera detection memory store
LIVE_DETECTIONS = {
    "cam1": {"plate": "Scanning...", "owner": "Scanning...", "traffic": "heavy", "color": "#ff4d4d", "lat": 28.5355, "lng": 77.3910},
    "cam2": {"plate": "Scanning...", "owner": "Scanning...", "traffic": "medium", "color": "#ffa500", "lat": 28.5412, "lng": 77.3980},
    "cam3": {"plate": "Scanning...", "owner": "Scanning...", "traffic": "low", "color": "#2ed573", "lat": 28.5280, "lng": 77.3850},
    "cam4": {"plate": "Scanning...", "owner": "Scanning...", "traffic": "medium", "color": "#ffa500", "lat": 28.5670, "lng": 77.3810},
}

CAMERA_INFO = {
    "cam1": {"name": "CAM 01 - Vishesh Tyagi Chowk", "lat": 28.522604, "lng": 77.392690},
    "cam2": {"name": "CAM 02 - Maharishi Ashram Chowk", "lat": 28.535266, "lng": 77.385753},
    "cam3": {"name": "CAM 03 - Bhangel", "lat": 28.541272, "lng": 77.387612},
    "cam4": {"name": "CAM 04 - Metro Sec 76", "lat": 28.566056, "lng": 77.379944},
}
TRAFFIC_WINDOW_SECONDS = 60
DETECTION_WRITE_INTERVAL_SECONDS = 5
TRAFFIC_CSV_LOCK = threading.Lock()
VEHICLE_CLASS_IDS = {2, 3, 5, 7}


def traffic_level(vehicle_count: int):
    if vehicle_count <= 10:
        return "low", "#2196f3"
    if vehicle_count <= 15:
        return "medium", "#ff9800"
    return "high", "#f44336"


def is_recent_detection(row: dict, now: datetime | None = None) -> bool:
    """Keep only detections recorded during the current rolling time window."""
    try:
        detection_time = datetime.strptime(str(row.get("time", "")).strip(), "%H:%M:%S")
    except ValueError:
        return False
    current = now or datetime.now()
    current_seconds = current.hour * 3600 + current.minute * 60 + current.second
    detection_seconds = detection_time.hour * 3600 + detection_time.minute * 60 + detection_time.second
    age_seconds = (current_seconds - detection_seconds) % (24 * 60 * 60)
    return age_seconds <= TRAFFIC_WINDOW_SECONDS


def read_distinct_vehicle_counts():
    """Count unique plates seen by each camera during the current time window."""
    counts = {camera_id: 0 for camera_id in CAMERA_INFO}
    if not os.path.isdir(TRAFFIC_CSV_DIR):
        return counts

    for filename in os.listdir(TRAFFIC_CSV_DIR):
        if not filename.endswith("_traffic.csv"):
            continue
        camera_id = filename.removesuffix("_traffic.csv")
        plates = set()
        csv_path = os.path.join(TRAFFIC_CSV_DIR, filename)
        try:
            with open(csv_path, encoding="utf-8", newline="") as csv_file:
                for row in csv.DictReader(csv_file):
                    if not is_recent_detection(row):
                        continue
                    plate = str(row.get("plate_number", "")).strip().upper()
                    if plate:
                        plates.add(plate)
        except (OSError, UnicodeDecodeError, csv.Error):
            # The detector may be replacing or appending to this file now.
            continue
        counts[camera_id] = len(plates)
    return counts


def read_latest_vehicle_plates():
    """Return the newest recent plate for each camera CSV."""
    latest = {}
    if not os.path.isdir(TRAFFIC_CSV_DIR):
        return latest

    for filename in os.listdir(TRAFFIC_CSV_DIR):
        if not filename.endswith("_traffic.csv"):
            continue
        camera_id = filename.removesuffix("_traffic.csv")
        csv_path = os.path.join(TRAFFIC_CSV_DIR, filename)
        try:
            with open(csv_path, encoding="utf-8", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            for row in reversed(rows):
                if not is_recent_detection(row):
                    continue
                plate = str(row.get("plate_number", "")).strip().upper()
                if plate:
                    latest[camera_id] = plate
                    break
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    return latest


def append_runtime_detection(camera_id: str, vehicle_id: str):
    """Append a live vehicle encounter for the traffic heatmap."""
    csv_path = os.path.join(TRAFFIC_CSV_DIR, f"{camera_id}_traffic.csv")
    os.makedirs(TRAFFIC_CSV_DIR, exist_ok=True)
    row = {"plate_number": vehicle_id, "time": datetime.now().strftime("%H:%M:%S")}
    with TRAFFIC_CSV_LOCK:
        file_exists = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
        with open(csv_path, "a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["plate_number", "time"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


def lookup_vehicle(plate_number: str):
    """Fetch owner details from vehicle_data.csv"""
    plate_clean = plate_number.upper().strip()
    if os.path.exists(CSV_PATH):
        try:
            df = pd.read_csv(CSV_PATH)
            df.columns = df.columns.str.strip()
            if "plate_number" in df.columns:
                df["plate_number"] = df["plate_number"].astype(str).str.strip().str.upper()
                match = df[df["plate_number"] == plate_clean]
                if not match.empty:
                    row = match.iloc[0].to_dict()
                    return {
                        "plate": plate_clean,
                        "owner": row.get("owner_name", row.get("owner", "Registered Owner")),
                    }
        except Exception as e:
            print(f"Error reading vehicle_data.csv: {e}")

    return {
        "plate": plate_clean,
        "owner": "Verified Owner" if PLATE_REGEX.match(plate_clean) else "Unknown Owner"
    }


def get_random_db_plate():
    """Reads vehicle_data.csv and picks a vehicle entry."""
    if os.path.exists(CSV_PATH):
        try:
            df = pd.read_csv(CSV_PATH)
            if "plate_number" in df.columns:
                sample_plates = df["plate_number"].dropna().tolist()
                if sample_plates:
                    chosen = str(random.choice(sample_plates)).strip().upper()
                    return lookup_vehicle(chosen)
        except Exception:
            pass
    
    defaults = [
        {"plate": "UP16 AB 1234", "owner": "Rahul Sharma"},
        {"plate": "DL3C XY 9876", "owner": "Amit Verma"},
        {"plate": "HR26 PQ 4567", "owner": "Priya Singh"},
        {"plate": "UP14 CD 5555", "owner": "Vikram Gupta"}
    ]
    return random.choice(defaults)


def get_video_files():
    video_files = []
    if not os.path.isdir(VIDEO_DIR):
        return video_files
    for filename in os.listdir(VIDEO_DIR):
        match = re.fullmatch(r"video(\d+)\.mp4", filename, re.IGNORECASE)
        if match:
            video_files.append((int(match.group(1)), os.path.join(VIDEO_DIR, filename)))
    return [path for _, path in sorted(video_files)]


def generate_frames(cam_key: str, starting_video_number: int):
    video_files = get_video_files()
    if not video_files:
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(blank, "No video footage found", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        _, buffer = cv2.imencode(".jpg", blank)
        while True:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

    starting_index = (starting_video_number - 1) % len(video_files)
    video_index = starting_index
    frame_counter = 0
    next_vehicle_id = 1
    active_tracks = {}
    max_missed_frames = 8
    last_written = {}

    while True:
        video_path = video_files[video_index]
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            video_index = (video_index + 1) % len(video_files)
            continue

        while True:
            success, frame = cap.read()
            if not success:
                break

            frame_counter += 1

            # Run Object Detection and keep a lightweight per-camera vehicle track.
            results = model(frame, conf=0.45, verbose=False)
            detections = []

            for r in results:
                for box in r.boxes:
                    class_id = int(box.cls[0]) if box.cls is not None else -1
                    if class_id not in VEHICLE_CLASS_IDS:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    center = ((x1 + x2) // 2, (y1 + y2) // 2)
                    detections.append((x1, y1, x2, y2, conf, center))

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame,
                        f"TARGET {conf:.2f}",
                        (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )

            current_time = datetime.now()
            matched_track_ids = set()
            frame_height, frame_width = frame.shape[:2]
            max_distance = max(50, int(min(frame_width, frame_height) * 0.12))
            for _, _, _, _, _, center in detections:
                nearest_id = None
                nearest_distance = max_distance
                for track_id, track in active_tracks.items():
                    if track_id in matched_track_ids:
                        continue
                    previous_center = track["center"]
                    distance = ((center[0] - previous_center[0]) ** 2 + (center[1] - previous_center[1]) ** 2) ** 0.5
                    if distance < nearest_distance:
                        nearest_id = track_id
                        nearest_distance = distance
                if nearest_id is None:
                    nearest_id = next_vehicle_id
                    next_vehicle_id += 1
                matched_track_ids.add(nearest_id)
                active_tracks[nearest_id] = {"center": center, "missed": 0}
                vehicle_id = f"{cam_key.upper()}-V{nearest_id:03d}"
                last_time = last_written.get(nearest_id)
                if last_time is None or (current_time - last_time).total_seconds() >= DETECTION_WRITE_INTERVAL_SECONDS:
                    append_runtime_detection(cam_key, vehicle_id)
                    last_written[nearest_id] = current_time

            for track_id, track in active_tracks.items():
                if track_id not in matched_track_ids:
                    track["missed"] += 1
            active_tracks = {
                track_id: track
                for track_id, track in active_tracks.items()
                if track["missed"] <= max_missed_frames
            }

            _, buffer = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

        cap.release()
        active_tracks.clear()
        video_index = (video_index + 1) % len(video_files)


@app.get("/video_feed/{cam_id}")
async def video_feed(cam_id: int):
    cam_key = f"cam{cam_id}"
    return ClientSafeStreamingResponse(
        generate_frames(cam_key, cam_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/live-detections")
async def live_detections():
    latest_plates = read_latest_vehicle_plates()
    return {
        camera_id: {
            **data,
            "plate": latest_plates.get(camera_id, "--"),
            "vehicle_id": latest_plates.get(camera_id, "--"),
        }
        for camera_id, data in LIVE_DETECTIONS.items()
    }


@app.get("/api/traffic-data")
async def traffic_data():
    formatted_data = []
    counts = read_distinct_vehicle_counts()
    for key, info in CAMERA_INFO.items():
        level, color = traffic_level(counts[key])
        formatted_data.append({
            "id": key,
            "name": info["name"],
            "lat": info["lat"],
            "lng": info["lng"],
            "vehicle_count": counts[key],
            "traffic_level": level,
            "color": color,
        })
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_seconds": TRAFFIC_WINDOW_SECONDS,
        "cameras": formatted_data,
    }


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/map.html", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="map.html")


# Keep the existing frontend's relative CSS, JavaScript, and map URLs working
# when this app is mounted by menu/app.py at /traffic.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="traffic_frontend")
