import cv2
from ultralytics import YOLO

try:
    from bounding_boxes import create_bounding_boxes, draw_bounding_boxes
except ImportError:
    from backend.bounding_boxes import create_bounding_boxes, draw_bounding_boxes


target_track_id = None
lost_frames = 0
MAX_LOST_FRAMES = 60

video_path = "backend/videos/vid1.mp4"

model = YOLO("yolo11n.pt")

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
        status = f"Target missing: {lost_frames}/{MAX_LOST_FRAMES}"

        if lost_frames == 1:
            print("Target lost. Reidentification would start here.")

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