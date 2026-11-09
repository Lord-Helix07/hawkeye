# HawkEye main file
#
## Week 1 Additions: added vehicle-detection pipeline entry point.
#Processes a pursuit video with YOLO11 and writes a new video containing
#labeled vehicle bounding boxes for target selection.


from pathlib import Path

import cv2

# import functions we need
try:
    from bounding_boxes import create_bounding_boxes, draw_bounding_boxes
    from byte_track import TrackState, follow_target, reset_tracker, track_vehicles
    from drone_distance import (
        PI_CAMERA_3_6MM,
        STAND_IN_TELEMETRY,
        distance_from_car_center,
        ground_distance_m,
    )
except ImportError:
    from backend.drone.bounding_boxes import create_bounding_boxes, draw_bounding_boxes
    from backend.drone.byte_track import TrackState, follow_target, reset_tracker, track_vehicles
    from backend.drone.drone_distance import (
        PI_CAMERA_3_6MM,
        STAND_IN_TELEMETRY,
        distance_from_car_center,
        ground_distance_m,
    )

#input/output video paths
VIDEOS_DIRECTORY = Path(__file__).parent / "videos"
INPUT_VIDEO = VIDEOS_DIRECTORY / "dashcam.mp4"
OUTPUT_VIDEO = VIDEOS_DIRECTORY / "dashcam_annotated.mp4"

#go through the video frame by frame --> handle errors along the way
# --> run tissas code and plug it onto the actual video file (output)

def _flight_telemetry(overrides):
    telemetry = dict(STAND_IN_TELEMETRY)
    if overrides:
        telemetry.update(overrides)
    return telemetry


def _draw_pursuit_status(frame, status, pixel_distance, gps):
    lines = [status]
    if pixel_distance is not None:
        lines.append(f"{pixel_distance['distance_px']:.0f} px from image center")
    if gps is not None:
        lines.append(f"GPS {gps['latitude']:.6f}, {gps['longitude']:.6f}")
    y = 40
    for line in lines:
        cv2.putText(
            frame,
            line,
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        y += 30
    return frame


def process_frame(frame, state, camera=None, telemetry=None):
    """Run one frame through tracking, boxes, the car center, and ground GPS."""
    camera = PI_CAMERA_3_6MM if camera is None else camera
    telemetry = _flight_telemetry(telemetry)

    # 1. Object detection and ByteTrack ids, on the shared YOLO model.
    detections = track_vehicles(frame)
    # 2. Box id, corners, and the car center.
    vehicles = create_bounding_boxes(detections)
    # 3. Keep the selected car, or reidentify it after its track id drops.
    target = follow_target(frame, vehicles, state)

    pixel_distance = None
    gps = None
    if target is not None:
        frame_height, frame_width = frame.shape[:2]
        # 4. Pixel offset from the middle of the frame to the car center.
        pixel_distance = distance_from_car_center(
            frame_width,
            frame_height,
            target["center_x"],
            target["center_y"],
        )
        package = {
            "photo": frame,
            "center_x": target["center_x"],
            "center_y": target["center_y"],
            **telemetry,
        }
        # 5. Meters on the ground, then the GPS point to fly toward.
        try:
            gps = ground_distance_m(package, camera)
        except ValueError:
            gps = None

    # 6. Draw every vehicle. The target is red.
    selected_box_id = None if target is None else target["box_id"]
    annotated = draw_bounding_boxes(frame, vehicles, selected_box_id=selected_box_id)
    _draw_pursuit_status(annotated, state.status, pixel_distance, gps)
    return {
        "frame": annotated,
        "vehicles": vehicles,
        "target": target,
        "pixel_distance": pixel_distance,
        "gps": gps,
        "status": state.status,
    }


#Note from Shivaji: Fixed it up to create a new video with the annotated bounding boxes
def process_video(
    input_path=INPUT_VIDEO,
    output_path=OUTPUT_VIDEO,
    camera=None,
    telemetry=None,
):
    """Detect, track, locate, and save an annotated pursuit video."""
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

    reset_tracker()
    state = TrackState()
    processed_frames = 0
    total_detections = 0
    last_status = state.status
    last_gps = None

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            outcome = process_frame(frame, state, camera=camera, telemetry=telemetry)
            writer.write(outcome["frame"])

            processed_frames += 1
            total_detections += len(outcome["vehicles"])
            last_status = outcome["status"]
            if outcome["gps"] is not None:
                last_gps = outcome["gps"]
    finally:
        capture.release()
        writer.release()

    print(f"Processed frames: {processed_frames}")
    print(f"Total vehicle detections: {total_detections}")
    print(f"Last status: {last_status}")
    if last_gps is not None:
        print(f"Last target GPS: {last_gps['latitude']}, {last_gps['longitude']}")
    print(f"Annotated video saved to: {output_path}")

    return output_path


if __name__ == "__main__":
    process_video()
