import cv2
from ultralytics import YOLO

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

    # Some frames may not have tracking IDs
    if result.boxes.id is not None:
        boxes = result.boxes.xyxy.int().cpu().tolist()
        track_ids = result.boxes.id.int().cpu().tolist()

        for box, track_id in zip(boxes, track_ids):
            x1, y1, x2, y2 = box

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                f"Vehicle ID: {track_id}",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

    cv2.imshow("ByteTrack Test", frame)

    if cv2.waitKey(30) & 0xFF == ord("q"):
        break

#Pressing q stops the program
cv2.destroyAllWindows()