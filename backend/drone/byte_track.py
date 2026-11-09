from pathlib import Path

import cv2
import numpy as np

try:
    from bounding_boxes import create_bounding_boxes, draw_bounding_boxes
    from object_detection import detections_from_result, model
except ImportError:
    from backend.drone.bounding_boxes import create_bounding_boxes, draw_bounding_boxes
    from backend.drone.object_detection import detections_from_result, model

MAX_LOST_FRAMES = 60
TRACKER_CONFIG = str(Path(__file__).parent / "bytetrack_custom.yaml")
DEFAULT_VIDEO = Path(__file__).parent / "videos" / "vid1.mp4"


class TrackState:
    """Target chosen for the current pursuit, and how long it has been missing."""

    def __init__(self):
        self.target_track_id = None
        self.lost_frames = 0
        self.target_features = None
        self.target_box = None
        self.status = "Waiting for a vehicle..."


def reset_tracker():
    """Drop ByteTrack's memory so the next video starts with new ids."""
    if getattr(model, "predictor", None) is not None:
        model.predictor = None


def track_vehicles(frame):
    """Detect vehicles and assign ByteTrack ids for this frame."""
    results = model.track(
        frame,
        persist=True,
        tracker=TRACKER_CONFIG,
        classes=[2, 3, 5, 7],
        verbose=False,
    )
    detections = detections_from_result(results[0])
    return [detection for detection in detections if "track_id" in detection]


def get_vehicle_features(frame, detection):
    """Save simple appearance features for one vehicle."""

    x1 = max(0, round(detection["x1"]))
    y1 = max(0, round(detection["y1"]))
    x2 = round(detection["x2"])
    y2 = round(detection["y2"])

    crop = frame[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    colored_pixels = hsv[
        (hsv[:, :, 1] > 40) &
        (hsv[:, :, 2] > 40)
    ]

    if len(colored_pixels) > 0:
        average_hue = float(np.mean(colored_pixels[:, 0]))
    else:
        average_hue = 0.0

    width = detection["width"]
    height = detection["height"]

    return {
        "average_hue": average_hue,
        "aspect_ratio": width / max(height, 1),
        "area": width * height,
    }


def compare_features(target_features, candidate_features):
    """Return how similar two vehicles are. Lower score is better."""

    hue_difference = abs(
        target_features["average_hue"]
        - candidate_features["average_hue"]
    ) / 180

    shape_difference = abs(
        target_features["aspect_ratio"]
        - candidate_features["aspect_ratio"]
    )

    area_difference = abs(
        target_features["area"]
        - candidate_features["area"]
    ) / max(target_features["area"], 1)

    return (
        0.5 * hue_difference
        + 0.3 * shape_difference
        + 0.2 * area_difference
    )


def _center(box):
    if "center_x" in box and "center_y" in box:
        return box["center_x"], box["center_y"]
    return (box["x1"] + box["x2"]) / 2, (box["y1"] + box["y2"]) / 2


def same_neighborhood(detection, last_box):
    """True when a car is within a few car-lengths of where the target was last seen."""
    last_cx, last_cy = _center(last_box)
    cx, cy = _center(detection)
    reach = max(last_box["width"], last_box["height"]) * 3
    return np.hypot(cx - last_cx, cy - last_cy) <= reach


def find_reidentified_vehicle(frame, detections, target_features, last_box):
    """Find the nearby vehicle most similar to the lost target."""

    if last_box is None:
        return None

    best_match = None
    best_score = float("inf")

    for detection in detections:
        if not same_neighborhood(detection, last_box):
            continue

        candidate_features = get_vehicle_features(frame, detection)

        if candidate_features is None:
            continue

        score = compare_features(
            target_features,
            candidate_features
        )

        if score < best_score:
            best_score = score
            best_match = detection

    # Reject matches that are not similar enough
    if best_score <= 0.5:
        return best_match

    return None


def follow_target(frame, vehicles, state):
    """Keep the selected vehicle, or reidentify it after ByteTrack drops the id."""
    visible_ids = {vehicle["box_id"] for vehicle in vehicles}

    if state.target_track_id is None:
        if len(vehicles) == 0:
            state.status = "Waiting for a vehicle..."
            return None

        target = vehicles[0]
        state.target_track_id = target["box_id"]
        state.target_box = target
        state.target_features = get_vehicle_features(frame, target)
        state.lost_frames = 0
        state.status = f"Tracking target ID {state.target_track_id}"
        print(f"Target selected: Vehicle ID {state.target_track_id}")
        return target

    if state.target_track_id in visible_ids:
        state.lost_frames = 0
        target = next(
            vehicle for vehicle in vehicles
            if vehicle["box_id"] == state.target_track_id
        )
        state.target_box = target
        state.status = f"Tracking target ID {state.target_track_id}"
        return target

    state.lost_frames += 1
    if state.lost_frames == 1:
        print("Target lost. Reidentification started.")

    if state.target_features is not None and state.lost_frames <= MAX_LOST_FRAMES:
        reidentified_vehicle = find_reidentified_vehicle(
            frame,
            vehicles,
            state.target_features,
            state.target_box,
        )
        if reidentified_vehicle is not None:
            state.target_track_id = reidentified_vehicle["box_id"]
            state.target_box = reidentified_vehicle
            state.target_features = get_vehicle_features(frame, reidentified_vehicle)
            state.lost_frames = 0
            state.status = f"Target reidentified as ID {state.target_track_id}"
            print(state.status)
            return reidentified_vehicle

    state.status = f"Target missing: {state.lost_frames}/{MAX_LOST_FRAMES}"
    if state.lost_frames >= MAX_LOST_FRAMES:
        state.status = "Target lost completely."
    return None


def preview_video(video_path=DEFAULT_VIDEO):
    """Show tracking on a video. The pursuit pipeline itself lives in main.py."""
    reset_tracker()
    state = TrackState()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Could not open input video: {video_path}")

    while True:
        success, frame = capture.read()
        if not success:
            break

        detections = track_vehicles(frame)
        vehicles = create_bounding_boxes(detections)
        target = follow_target(frame, vehicles, state)
        selected_box_id = None if target is None else target["box_id"]
        frame = draw_bounding_boxes(frame, vehicles, selected_box_id=selected_box_id)
        cv2.putText(
            frame,
            state.status,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        cv2.imshow("ByteTrack Test", frame)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break

    capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    preview_video()
