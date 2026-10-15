import cv2
from pathlib import Path
from backend.YOLO11_Object_detection.Yolo11_object_detection import detect_vehicles

video_path = Path(__file__).parent.parent / "videos" / "dashcam.mp4"
capture = cv2.VideoCapture(str(video_path))

print("Video opened:", capture.isOpened())

success, frame = capture.read()
print("Frame read:", success)

if success:
    detected_vehicles = detect_vehicles(frame)
    print("Total vehicles:", len(detected_vehicles))
    for vehicle in detected_vehicles:
        print(vehicle)

capture.release()

