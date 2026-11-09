# ASSIGNED TO: Pranav
# Vehicle object detection and model training/testing work.
# This will be used to detect vehicles from camera frames.

#  All imports
from pathlib import Path

import cv2
from ultralytics import YOLO


#  Load the YOLO11 model that sits next to this file.
model = YOLO(str(Path(__file__).with_name("yolo11n.pt")))
print("YOLO11 model loaded successfully")


def detections_from_result(result):
    """Turn one YOLO result into vehicle dicts. Includes track_id when ByteTrack set one."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []

    xyxy = boxes.xyxy.cpu().tolist()
    classes = boxes.cls.int().cpu().tolist()
    confidences = boxes.conf.cpu().tolist()
    if boxes.id is None:
        track_ids = [None] * len(xyxy)
    else:
        track_ids = boxes.id.int().cpu().tolist()

    vehicles = []
    for box, class_id, confidence, track_id in zip(xyxy, classes, confidences, track_ids):
        class_name = model.names[class_id]
        if class_name not in ("car", "motorcycle", "bus", "truck"):
            continue

        x1, y1, x2, y2 = box
        detection = {
            #Note from Shivaji: Tissa's code requires id,width,height --> plugging those into pranavs code
            "class_id": class_id,
            "class_name": class_name,
            "confidence": confidence,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "width": x2 - x1,
            "height": y2 - y1,
        }
        if track_id is not None:
            detection["track_id"] = track_id
        vehicles.append(detection)

    return vehicles


# Function to detect vehicles in a given frame and stores it in vehicles list
def detect_vehicles(frame):
    """Detect supported vehicle classes and return their box coordinates."""
    results = model(frame, classes=[2, 3, 5, 7])
    return detections_from_result(results[0])


# Load a test frame and detect vehicles
if __name__ == "__main__":
    image_path = Path(__file__).parent / "test_frame.png"
    frame = cv2.imread(str(image_path))
    print(frame.shape)
    detected_vehicles = detect_vehicles(frame)
    print("Total vehicles:", len(detected_vehicles))
    for vehicle in detected_vehicles:
        print(vehicle)
