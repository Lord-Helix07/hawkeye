import cv2
from ultralytics import YOLO

try:
    from bounding_boxes import create_bounding_boxes, draw_bounding_boxes
except ImportError:
    from backend.bounding_boxes import create_bounding_boxes, draw_bounding_boxes

# Ask for a test vehicle video
video_path = "backend/videos/vid1.mp4"

# Load YOLO once
model = YOLO("yolo11n.pt")

# ByteTrack processes the video frame by frame
results = model.track(
    source=video_path,
    stream=True,
    persist=True,
    tracker="bytetrack.yaml",
    classes=[2, 3, 5, 7],
    verbose=False
)

for result in results:
    frame = result.orig_img.copy()
    detections = []

    # Some frames may not have tracking IDs
    if result.boxes is not None and result.boxes.id is not None:
        boxes = result.boxes.xyxy.cpu().tolist()
        classes = result.boxes.cls.int().cpu().tolist()
        confidences = result.boxes.conf.cpu().tolist()
        track_ids = result.boxes.id.int().cpu().tolist()
        #changed the box drawing logic to use the bounding_boxes.py file
        for box, class_id, confidence, track_id in zip(boxes, classes, confidences, track_ids):
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
    frame = draw_bounding_boxes(frame, vehicles)

    cv2.imshow("ByteTrack Test", frame)

    if cv2.waitKey(30) & 0xFF == ord("q"):
        break

#Pressing q stops the program
cv2.destroyAllWindows()
