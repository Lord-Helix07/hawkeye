# ASSIGNED TO: Pranav
# Vehicle object detection and model training/testing work.
# This will be used to detect vehicles from camera frames.

#  All imports
from pathlib import Path

import cv2
from ultralytics import YOLO


#  Load the YOLO11 model
model = YOLO("yolo11n.pt")
print("YOLO11 model loaded successfully")


# Function to detect vehicles in a given frame and stores it in vehicles list
def detect_vehicles(frame):
    """Detect supported vehicle classes and return their box coordinates."""
    results = model(frame, classes=[2, 3, 5, 7])
    boxes = results[0].boxes
    vehicles = []

    for box in boxes:
        class_id = int(box.cls[0])
        class_name = model.names[class_id]
        if class_name not in ("car", "motorcycle", "bus", "truck"):
            continue

        confidence = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        vehicles.append({
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
        })

    return vehicles


# Load a test frame and detect vehicles
if __name__ == "__main__":
    image_path = Path(__file__).parent / "test_frame.png"
    frame = cv2.imread(str(image_path))
    print(frame.shape)
    detected_vehicles = detect_vehicles(frame)
    print("Total vehicles:", len(detected_vehicles))
    for vehicle in detected_vehicles:
        print(vehicle)
