import cv2
from ultralytics import YOLO
import numpy as np

try:
    from bounding_boxes import create_bounding_boxes, draw_bounding_boxes
except ImportError:
    from backend.bounding_boxes import create_bounding_boxes, draw_bounding_boxes

target_track_id = None
lost_frames = 0
MAX_LOST_FRAMES = 60
target_features = None

video_path = "backend/videos/vid1.mp4"

model = YOLO("yolo11n.pt")

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


def find_reidentified_vehicle(frame, detections, target_features):
    """Find the visible vehicle most similar to the lost target."""

    best_match = None
    best_score = float("inf")

    for detection in detections:
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


results = model.track(
    source=video_path,
    stream=True,
    persist=True,
    tracker="backend/bytetrack_custom.yaml",
    classes=[2, 3, 5, 7],
    verbose=False
)

for result in results:
    frame = result.orig_img.copy()
    detections = []

    if result.boxes is not None and result.boxes.id is not None:
        boxes = result.boxes.xyxy.cpu().tolist()
        classes = result.boxes.cls.int().cpu().tolist()
        confidences = result.boxes.conf.cpu().tolist()
        track_ids = result.boxes.id.int().cpu().tolist()

        for box, class_id, confidence, track_id in zip(
            boxes,
            classes,
            confidences,
            track_ids
        ):
            x1, y1, x2, y2 = box

            detections.append({
                "track_id": track_id,
                "class_id": class_id,
                "class_name": model.names[class_id],
                "confidence": confidence,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "width": x2 - x1,
                "height": y2 - y1,
            })

    vehicles = create_bounding_boxes(detections)

    visible_ids = {
        detection["track_id"]
        for detection in detections
    }

    # Temporarily select the first vehicle for testing
    if target_track_id is None:
        if len(detections) > 0:
            target_track_id = detections[0]["track_id"]
            target_features = get_vehicle_features(frame, detections[0])
            print(f"Target selected: Vehicle ID {target_track_id}")
            status = f"Tracking target ID {target_track_id}"
        else:
            status = "Waiting for a vehicle..."

    # Check whether the target is visible
    elif target_track_id in visible_ids:
        lost_frames = 0
        status = f"Tracking target ID {target_track_id}"

    # Target is missing
    else:
        lost_frames += 1

        if lost_frames == 1:
            print("Target lost. Reidentification started.")

        # Only try ReID while the target is missing
        if (
            target_features is not None
            and lost_frames <= MAX_LOST_FRAMES
        ):
            reidentified_vehicle = find_reidentified_vehicle(
                frame,
                detections,
                target_features
            )

            if reidentified_vehicle is not None:
                target_track_id = reidentified_vehicle["track_id"]

                target_features = get_vehicle_features(frame,reidentified_vehicle)

                lost_frames = 0
                status = f"Target reidentified as ID {target_track_id}"
                print(status)
            else:
                status = f"Target missing: {lost_frames}/{MAX_LOST_FRAMES}"

        else:
            status = f"Target missing: {lost_frames}/{MAX_LOST_FRAMES}"

        if lost_frames >= MAX_LOST_FRAMES:
            status = "Target lost completely."

    # Draw all normal vehicle boxes
    frame = draw_bounding_boxes(frame, vehicles)

    # Draw the target with a red box
    for detection in detections:
        if detection["track_id"] == target_track_id:
            x1 = round(detection["x1"])
            y1 = round(detection["y1"])
            x2 = round(detection["x2"])
            y2 = round(detection["y2"])

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 0, 255),
                3
            )

            cv2.putText(
                frame,
                f"TARGET ID: {target_track_id}",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )

    # Show the current status
    cv2.putText(
        frame,
        status,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2
    )

    cv2.imshow("ByteTrack Test", frame)

    if cv2.waitKey(30) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()