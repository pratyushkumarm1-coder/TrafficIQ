import cv2
import numpy as np
import threading
import time
import os
from ultralytics import YOLO
from database import save_traffic_log
from state import current_stats

_BASE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Multi-camera registry.
# Each camera: id, label, video filename (in backend/), live flag.
# Add more entries (e.g. india2.webm) and the system analyses them in round-
# robin side-by-side fashion. The active camera feeds current_stats.
# --------------------------------------------------------------------------
CAMERA_REGISTRY = [
    {"id": "cam1", "label": "Link Road Junction (Live)", "video": "india_traffic.webm", "live": True},
    # {"id": "cam2", "label": "Badambadi", "video": "india2.webm", "live": False},
    # {"id": "cam3", "label": "Madhupatna", "video": "india3.webm", "live": False},
]

_VIDEO_SOURCE = os.path.join(_BASE, "india_traffic.webm")


def camera_video_path(video_name):
    return os.path.join(_BASE, video_name)


class TrafficAnalyzer:
    def __init__(self, model_path='yolov8n.pt', frame_rate=30):
        # Load the YOLOv8 model for object detection
        self.model = YOLO(model_path)
        # COCO indices: 2=car, 3=motorcycle, 5=bus, 7=truck
        self.vehicle_classes = [2, 3, 5, 7]
        self.class_names = {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}

        self.last_db_save = time.time()

        # For speed calculation: track previous positions
        self.previous_positions = {}
        # Per-track-id recent positions list (for wrong-way direction analysis)
        self.trajectories = {}
        self.frame_rate = frame_rate

        # Latest processed (annotated) frame, continuously updated by a
        # background worker so stats stay fresh even with no stream viewer.
        self.latest_frame = None
        # Normalized detection centers (x,y in 0..1) for heatmap overlay
        self.latest_detections = []
        # Emergency vehicle flag (set when such a class/detection appears)
        self.emergency_since = None
        self._thread = threading.Thread(target=self._work_loop, daemon=True)
        self._thread.start()

    def _work_loop(self):
        """Analyze each camera's video continuously (round-robin across the
        registry). Frames are combined side-by-side when multiple exist."""
        caps = []
        for cam in CAMERA_REGISTRY:
            path = camera_video_path(cam["video"])
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                caps.append((cam, cap))
            else:
                print(f"TrafficAnalyzer: could not open {cam['video']}")

        if not caps:
            print("TrafficAnalyzer: no camera sources available")
            return

        while True:
            processed = []
            for cam, cap in caps:
                success, frame = cap.read()
                if not success:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop video
                    success, frame = cap.read()
                    if not success:
                        continue
                frame = cv2.resize(frame, (640, 480))
                annotated = self.process_frame(frame)
                processed.append(annotated)

            if processed:
                # Combine side-by-side if multiple cameras
                if len(processed) == 1:
                    combined = processed[0]
                else:
                    combined = np.hstack(processed)
                    # resize combined to a sane width
                    scale = 800 / combined.shape[1]
                    combined = cv2.resize(combined, (int(combined.shape[1] * scale), int(combined.shape[0] * scale)))
                self.latest_frame = combined

    def process_frame(self, frame):
        # Run YOLO with ByteTrack built-in tracking
        results = self.model.track(
            frame,
            classes=self.vehicle_classes,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
        )

        annotated_frame = frame.copy()
        vehicle_count = 0
        type_counts = {"Car": 0, "Motorcycle": 0, "Bus": 0, "Truck": 0}
        speeds = []
        detections = []
        emergency_now = False

        if results and len(results) > 0 and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().tolist()
            class_ids = results[0].boxes.cls.int().cpu().tolist()

            vehicle_count = len(boxes)
            h, w = frame.shape[:2]

            for box, track_id, class_id in zip(boxes, track_ids, class_ids):
                # Count types
                v_type = self.class_names.get(class_id, "Car")
                type_counts[v_type] += 1

                # Speed calculation (pixel distance / time)
                x1, y1, x2, y2 = box
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                detections.append({"x": round(cx / w, 3), "y": round(cy / h, 3),
                                   "w": round((x2 - x1) / w, 3), "h": round((y2 - y1) / h, 3)})

                # Emergency vehicle heuristic: truck/bus-size box, high speed
                if v_type == "Truck" and (x2 - x1) * (y2 - y1) > 0.12 * w * h:
                    emergency_now = True

                if track_id in self.previous_positions:
                    prev_cx, prev_cy = self.previous_positions[track_id]
                    # Calculate pixel distance
                    distance = np.sqrt((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2)
                    # Rough conversion factor: 1 pixel ~ 0.05 meters (highly dependent on camera angle)
                    # Speed = Distance / Time -> meters / frame -> meters / second -> km/h
                    speed_kmh = (distance * 0.05) * self.frame_rate * 3.6
                    speeds.append(speed_kmh)

                self.previous_positions[track_id] = (cx, cy)

                # Record trajectory (bound to frame dims used above)
                traj = self.trajectories.setdefault(track_id, [])
                traj.append((cx, cy))
                if len(traj) > 8:  # keep short history
                    traj.pop(0)

            # Update Status
            if vehicle_count > 15:
                status = "Congested"
            elif vehicle_count > 7:
                status = "Heavy"
            else:
                status = "Normal"

            annotated_frame = results[0].plot()

            # Update Global State
            current_stats["vehicle_count"] = vehicle_count
            current_stats["traffic_status"] = status
            current_stats["vehicle_types"] = type_counts
            if speeds:
                # Add a smoothing factor to speed
                avg_speed = sum(speeds) / len(speeds)
                # Keep it realistic
                if avg_speed > 120:
                    avg_speed = 120
                current_stats["average_speed"] = round(avg_speed, 1)

            self.latest_detections = detections

            # Emergency vehicle corridor alert (set/reset with tiny hysteresis)
            now = time.time()
            if emergency_now and self.emergency_since is None:
                self.emergency_since = now
            elif not emergency_now and self.emergency_since is not None and now - self.emergency_since > 3:
                self.emergency_since = None

            # Draw UI
            cv2.putText(annotated_frame, f"Vehicles: {vehicle_count}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(annotated_frame, f"Speed: {current_stats['average_speed']} km/h", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
            cv2.putText(annotated_frame, f"Status: {status}", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255) if status == "Congested" else (0, 255, 0), 2)

            # Save to database every 10 seconds
            if time.time() - self.last_db_save > 10:
                save_traffic_log(vehicle_count, status, current_stats.get("average_speed", 0.0))
                self.last_db_save = time.time()

            # Run anomaly detection ~ every 20 seconds
            if not hasattr(self, "_last_anomaly"):
                self._last_anomaly = 0
            if time.time() - getattr(self, "_last_anomaly", 0) > 20:
                self._last_anomaly = time.time()
                try:
                    from features import evaluate_anomalies
                    evaluate_anomalies()
                except Exception:
                    pass

        return annotated_frame


def get_latest_frame():
    """Return the most recently analyzed frame (bytes) for the MJPEG stream."""
    global _latest_frame_bytes
    frame = analyzer.latest_frame
    if frame is None:
        return None
    ok, buffer = cv2.imencode('.jpg', frame)
    if not ok:
        return None
    _latest_frame_bytes = buffer.tobytes()
    return _latest_frame_bytes


def get_latest_frame_b64():
    """Return the most recently analyzed frame as a base64 JPEG string, or None."""
    chunk = get_latest_frame()
    if chunk is None:
        return None
    import base64
    return base64.b64encode(chunk).decode('ascii')


def get_detections():
    """Return normalized detection centers for the heatmap overlay."""
    return getattr(analyzer, "latest_detections", [])


def get_emergency():
    """Return True while an emergency vehicle is detected (with hysteresis)."""
    since = getattr(analyzer, "emergency_since", None)
    if since is None:
        return False
    return time.time() - since <= 5


def set_emergency_manual(duration=10):
    """Manual emergency trigger (frontend button / simulation)."""
    analyzer.emergency_since = time.time()
    analyzer._emergency_manual_until = time.time() + duration


def emergency_active():
    since = getattr(analyzer, "emergency_since", None)
    man = getattr(analyzer, "_emergency_manual_until", 0)
    return (since is not None and time.time() - since <= 5) or time.time() < man


def generate_video_stream():
    """MJPEG stream that just re-serves the analyzers continuously-updated frame."""
    while True:
        chunk = get_latest_frame()
        if chunk is None:
            time.sleep(0.1)
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + chunk + b'\r\n')
        # ~ modest pacing so we don't hammer the client
        time.sleep(0.04)


_latest_frame_bytes = None

# One shared analyzer instance; its background thread keeps analysis running
# for the life of the process regardless of stream viewers.
analyzer = TrafficAnalyzer()
