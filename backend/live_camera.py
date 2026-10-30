# HawkEye live camera pipeline (runs on the Raspberry Pi 5)
#
# Reads frames from the drone camera, runs vehicle detection + bounding boxes on
# every frame, and serves the results over HTTP so the frontend can watch live:
#   /           simple page showing the annotated stream
#   /stream     annotated MJPEG video
#   /detections latest bounding boxes as JSON
#
# Run from the repo root:
#   python -m backend.live_camera                      (Pi camera, or webcam 0 if no Pi camera)
#   python -m backend.live_camera --source 0           (USB webcam)
#   python -m backend.live_camera --source clip.mp4    (loop a video file for testing)
#
# How it fits together (3 things run at the same time):
#   1. Camera thread    -> keeps grabbing the newest frame from the camera
#   2. Detection thread -> takes the newest frame, runs YOLO + draws boxes, saves the result
#   3. Web server       -> sends the saved result to anyone watching in a browser
# They run separately so a slow YOLO frame never makes the camera or the website freeze.

import argparse
import threading
import time
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from backend.bounding_boxes import create_bounding_boxes, draw_bounding_boxes
from backend.object_detection import detect_vehicles


class Camera:
    """Keeps reading frames in the background so detection always gets the newest one."""

    def __init__(self, source="auto", width=1280, height=720):
        #only one of these gets used: picamera for the Pi camera, capture for webcams/video files
        self.picamera = None
        self.capture = None
        self.is_file = False
        self.file_delay = 0
        #if new frame + counteer to see if alr detected         
        self.frame = None
        self.frame_number = 0
        #lock stops the camera thread and detection thread from touching the frame at the same time
        self.lock = threading.Lock()
        self.running = True

        #try the Pi camera first, if it's not there use the first webcam instead
        if source in ("auto", "picamera"):
            try:
                self.open_picamera(width, height)
            except Exception as error:
                if source == "picamera":
                    raise
                print(f"No Pi camera found ({error}), falling back to webcam 0")
                source = "0"

        if self.picamera is None:
            self.open_opencv(source, width, height)

        #start reading frames in the background (daemon = it dies when the program exits)
        self.thread = threading.Thread(target=self.read_loop, daemon=True)
        self.thread.start()

    def open_picamera(self, width, height):
        from picamera2 import Picamera2

        self.picamera = Picamera2()
        # "RGB888" in libcamera is BGR byte order, which is what OpenCV expects
        config = self.picamera.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self.picamera.configure(config)
        self.picamera.start()
        print(f"Using Pi camera at {width}x{height}")

    def open_opencv(self, source, width, height):
        #"0", "1" etc. means a webcam number, anything else is a video file path or stream URL
        self.is_file = Path(source).is_file()
        self.capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open camera source: {source}")

        if self.is_file:
            #video files would play way too fast otherwise, so wait 1 frame's worth of time each read
            self.file_delay = 1 / (self.capture.get(cv2.CAP_PROP_FPS) or 30.0)
        else:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            #only keep 1 frame buffered so we never get old (laggy) frames
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print(f"Using OpenCV source: {source}")

    def read_one(self):
        """Grab one frame from whichever camera is open (None if it failed)."""
        if self.picamera is not None:
            return self.picamera.capture_array()

        success, frame = self.capture.read()
        #relooping for test
        if not success and self.is_file:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            success, frame = self.capture.read()
        if self.is_file:
            time.sleep(self.file_delay)
        return frame if success else None

    def read_loop(self):
        """Background loop: keep replacing self.frame with the newest camera frame."""
        while self.running:
            frame = self.read_one()
            if frame is None:
                #camera hiccup cgeck
                time.sleep(0.05)
                continue
            with self.lock:
                self.frame = frame
                self.frame_number += 1

    def latest(self):
        """Return (frame_number, frame) for the newest frame, or (0, None) before the first one."""
        with self.lock:
            return self.frame_number, self.frame

    def close(self):
        """Stop the background thread and release the camera so other programs can use it."""
        self.running = False
        self.thread.join(timeout=2)
        if self.picamera is not None:
            self.picamera.stop()
        if self.capture is not None:
            self.capture.release()


class LiveResults:
    """Latest annotated JPEG + detections, shared between the detection thread and the web server."""

    def __init__(self):
        #condition = a lock that can also wake up anyone waiting for a new frame (the video stream)
        self.condition = threading.Condition()
        self.jpeg = None
        self.vehicles = []
        self.fps = 0.0
        self.updated_at = None

    def update(self, jpeg, vehicles, fps):
        """Save the newest result and wake up every browser waiting on /stream."""
        with self.condition:
            self.jpeg = jpeg
            self.vehicles = vehicles
            self.fps = fps
            self.updated_at = time.time()
            self.condition.notify_all()

    def wait_for_jpeg(self, last_jpeg, timeout=1.0):
        """Wait until there's a frame newer than last_jpeg (gives up after timeout seconds)."""
        with self.condition:
            self.condition.wait_for(lambda: self.jpeg is not last_jpeg, timeout=timeout)
            return self.jpeg

    def snapshot(self):
        """The JSON the frontend gets from /detections."""
        with self.condition:
            return {
                "fps": round(self.fps, 1),
                "updated_at": self.updated_at,
                "vehicles": self.vehicles,
            }


def detection_loop(camera, results, image_size, stop_event):
    """Run detection on the newest camera frame over and over."""
    last_frame_number = 0
    fps = 0.0

    while not stop_event.is_set():
        #skip if the camera hasn't started yet or we already did this exact frame
        frame_number, frame = camera.latest()
        if frame is None or frame_number == last_frame_number:
            time.sleep(0.005)
            continue
        last_frame_number = frame_number

        #same pipeline as main.py: YOLO -> give each box an id -> draw the boxes
        start = time.monotonic()
        detections = detect_vehicles(frame, image_size)
        vehicles = create_bounding_boxes(detections)
        #copy so we don't draw on the frame the camera thread still owns
        annotated_frame = draw_bounding_boxes(frame.copy(), vehicles)

        # smooth the fps number so it doesn't jump around every frame
        frame_fps = 1 / max(time.monotonic() - start, 1e-6)
        fps = frame_fps if fps == 0 else fps * 0.9 + frame_fps * 0.1
        cv2.putText(
            annotated_frame,
            f"{fps:.1f} FPS",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        #compress to JPEG once here so every browser watching can reuse the same bytes
        success, jpeg = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if success:
            results.update(jpeg.tobytes(), vehicles, fps)


def create_app(results):
    """Build the web server with the 3 URLs listed at the top of this file."""
    app = FastAPI(title="HawkEye live camera")
    # the Vite frontend runs on a different port, so allow it to call this server
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    #basic test page, just shows the /stream video full width
    @app.get("/", response_class=HTMLResponse)
    def index():
        return (
            "<html><head><title>HawkEye live</title></head>"
            "<body style='margin:0;background:#000'>"
            "<img src='/stream' style='width:100%;height:auto'>"
            "</body></html>"
        )

    #MJPEG stream: one long response that keeps sending JPEGs, browsers show it as video
    #(frontend can use it with just <img src="http://<pi-ip>:8000/stream">)
    @app.get("/stream")
    def stream():
        def frames():
            jpeg = None
            while True:
                new_jpeg = results.wait_for_jpeg(jpeg)
                if new_jpeg is None or new_jpeg is jpeg:
                    continue
                jpeg = new_jpeg
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(
            frames(), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    #box coordinates/class/confidence for the target selection screen
    @app.get("/detections")
    def detections():
        return results.snapshot()

    return app


def main():
    #command line options (run with --help to see them all)
    parser = argparse.ArgumentParser(description="Live vehicle detection from the drone camera")
    parser.add_argument("--source", default="auto",
                        help="auto, picamera, a webcam index like 0, or a video file/URL")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--image-size", type=int, default=640,
                        help="YOLO input size; smaller is faster but misses far away cars "
                             "(320 lost ~45%% of detections in testing)")
    #0.0.0.0 = let other devices on the wifi connect, not just the Pi itself
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    #start the camera thread and the detection thread
    camera = Camera(args.source, args.width, args.height)
    results = LiveResults()
    stop_event = threading.Event()
    detector = threading.Thread(
        target=detection_loop,
        args=(camera, results, args.image_size, stop_event),
        daemon=True,
    )
    detector.start()

    #web server runs here until Ctrl+C, then the finally block shuts everything down cleanly
    print(f"Open http://<pi-ip>:{args.port}/ to watch the live stream")
    try:
        uvicorn.run(
            create_app(results),
            host=args.host,
            port=args.port,
            log_level="warning",
            timeout_graceful_shutdown=2,
        )
    finally:
        stop_event.set()
        detector.join(timeout=2)
        camera.close()


if __name__ == "__main__":
    main()
