# HawkEye main file 
# 
## Week 1 Additions: added vehicle-detection pipeline entry point.
#Processes a pursuit video with YOLO11 and writes a new video containing
#labeled vehicle bounding boxes for target selection.


from pathlib import Path

import cv2

# import functions we need
from backend.bounding_boxes import create_bounding_boxes, draw_bounding_boxes
from backend.object_detection import detect_vehicles

#input/output video paths
VIDEOS_DIRECTORY = Path(__file__).parent / "videos"
INPUT_VIDEO = VIDEOS_DIRECTORY / "dashcam.mp4"
OUTPUT_VIDEO = VIDEOS_DIRECTORY / "dashcam_annotated.mp4"

#go through the video frame by frame --> handle errors along the way 
# --> run tissas code and plug it onto the actual video file (output)

#Note from Shivaji: Fixed it up to create a new video with the annotated bounding boxes
def process_video(input_path=INPUT_VIDEO, output_path=OUTPUT_VIDEO):
    """Detect vehicles in every frame and save an annotated video."""
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Could not open input video: {input_path}")

    frame_width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames_per_second = capture.get(cv2.CAP_PROP_FPS) or 30.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        frames_per_second,
        (frame_width, frame_height),
    )

    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create output video: {output_path}")

    processed_frames = 0
    total_detections = 0

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            detections = detect_vehicles(frame)
            vehicles = create_bounding_boxes(detections)
            annotated_frame = draw_bounding_boxes(frame, vehicles)
            writer.write(annotated_frame)

            processed_frames += 1
            total_detections += len(vehicles)
    finally:
        capture.release()
        writer.release()

    print(f"Processed frames: {processed_frames}")
    print(f"Total vehicle detections: {total_detections}")
    print(f"Annotated video saved to: {output_path}")

    return output_path


if __name__ == "__main__":
    process_video()
