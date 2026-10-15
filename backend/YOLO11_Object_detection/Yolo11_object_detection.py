#  All imports
from ultralytics import YOLO
from pathlib import Path
import cv2

#  Load the YOLO11 model
model = YOLO("yolo11n.pt")
print("YOLO11 model loaded successfully")

# Function to detect vehicles in a given frame and stores it in vehicles list
def detect_vehicles(frame):
    results = model(frame, classes=[2, 3, 5, 7])
    boxes = results[0].boxes
    vehicles = []
    for box in boxes:
        class_id = int(box.cls[0])
        class_name = model.names[class_id]
        is_vehicle = class_name in ("car", "motorcycle", "bus", "truck")
        if is_vehicle:
            confidence = float(box.conf[0])
            coordinates = box.xyxy[0].tolist()
            x1, y1, x2, y2 = coordinates
            vehicle = {
                "class_name": class_name,
                "confidence": confidence,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2
                }
            vehicles.append(vehicle)
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