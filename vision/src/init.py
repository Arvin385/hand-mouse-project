import cv2
import mediapipe as mp
import os
from pathlib import Path
import subprocess
import time

from mediapipe.tasks.python import vision
from mediapipe.tasks.python import BaseOptions
from camera.config import (
    CAMERA_DEVICE,
    CAMERA_AUTO_EXPOSURE,
    CAMERA_EXPOSURE,
    CAMERA_GAIN,
)

# ============================================================
# CONFIGURATION
# ============================================================

MODEL_PATH = str(Path(__file__).resolve().with_name("hand_landmarker.task"))

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_FORMAT = "MJPG"


# Frames discarded while the camera settles.
CAMERA_WARMUP_FRAMES = 10


# ============================================================
# APPLICATION INITIALIZER
# ============================================================

class HandMouseInit:
    """
    Initializes and owns the hardware/resources used by
    the hand mouse application.

    Responsibilities:
        - Verify MediaPipe model
        - Initialize MediaPipe GPU
        - Open/configure webcam
        - Apply V4L2 camera controls
        - Warm up camera
        - Verify camera + MediaPipe pipeline
        - Provide frames and hand detections to engine.py
        - Clean up resources
    """

    def __init__(self):
        self.camera = None
        self.landmarker = None

        self.started = False

        # MediaPipe VIDEO mode requires strictly increasing
        # timestamps.
        self.timestamp_origin = None
        self.last_timestamp_ms = 0

    # ========================================================
    # PUBLIC API
    # ========================================================

    def start(self):
        """
        Initialize all application resources.

        Returns:
            HandMouseInit: this initialized instance.
        """

        print()
        print("========================================")
        print(" Jetson Hand Mouse - Initialization")
        print("========================================")
        print()

        try:
            self._check_model()
            self._initialize_mediapipe()
            self._initialize_camera()
            self._warmup_camera()
            self._run_self_test()

            # The self-test uses timestamp 0.
            # Runtime timestamps must begin above that.
            self.timestamp_origin = time.monotonic()
            self.last_timestamp_ms = 0

            self.started = True

            print()
            print("========================================")
            print(" Initialization successful")
            print("========================================")
            print()

            return self

        except Exception:
            print()
            print("Initialization FAILED.")
            print("Cleaning up resources...")

            self.shutdown()
            raise

    def read_frame(self):
        """
        Capture and return the next webcam frame.

        Returns:
            numpy.ndarray: OpenCV BGR frame.

        Raises:
            RuntimeError: If the camera is unavailable or
                          frame capture fails.
        """

        if self.camera is None:
            raise RuntimeError(
                "Camera has not been initialized."
            )

        success, frame = self.camera.read()

        if not success or frame is None:
            raise RuntimeError(
                "Failed to read frame from webcam."
            )

        return frame

    def get_timestamp_ms(self):
        """
        Return a strictly increasing timestamp in milliseconds
        for MediaPipe VIDEO mode.
        """

        if self.timestamp_origin is None:
            raise RuntimeError(
                "Timestamp clock has not been initialized."
            )

        timestamp_ms = int(
            (
                time.monotonic()
                - self.timestamp_origin
            )
            * 1000
        )

        # MediaPipe requires timestamps to always increase.
        if timestamp_ms <= self.last_timestamp_ms:
            timestamp_ms = self.last_timestamp_ms + 1

        self.last_timestamp_ms = timestamp_ms

        return timestamp_ms

    def detect_hands(self, frame):
        """
        Run MediaPipe HandLandmarker against an OpenCV frame.

        Args:
            frame:
                OpenCV BGR image.

        Returns:
            MediaPipe HandLandmarkerResult.
        """

        if self.landmarker is None:
            raise RuntimeError(
                "MediaPipe has not been initialized."
            )

        # OpenCV uses BGR.
        # MediaPipe expects RGB.
        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb
        )

        timestamp_ms = self.get_timestamp_ms()

        return self.landmarker.detect_for_video(
            mp_image,
            timestamp_ms
        )

    def shutdown(self):
        """
        Release all initialized resources.

        Safe to call multiple times.
        """

        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass

            self.camera = None

        if self.landmarker is not None:
            try:
                self.landmarker.close()
            except Exception:
                pass

            self.landmarker = None

        self.started = False
        self.timestamp_origin = None
        self.last_timestamp_ms = 0

    # ========================================================
    # MODEL
    # ========================================================

    def _check_model(self):
        print("[1/5] Checking hand landmark model...")

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"MediaPipe model not found: {MODEL_PATH}"
            )

        size_mb = (
            os.path.getsize(MODEL_PATH)
            / (1024 * 1024)
        )

        print(f"      Found: {MODEL_PATH}")
        print(f"      Size: {size_mb:.2f} MB")

    # ========================================================
    # MEDIAPIPE
    # ========================================================

    def _initialize_mediapipe(self):
        print("[2/5] Initializing MediaPipe GPU...")

        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(
                model_asset_path=MODEL_PATH,
                delegate=BaseOptions.Delegate.GPU
            ),

            running_mode=vision.RunningMode.VIDEO,

            num_hands=1,

            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.landmarker = (
            vision.HandLandmarker
            .create_from_options(options)
        )

        print(
            "      MediaPipe version:",
            mp.__version__
        )

        print(
            "      GPU HandLandmarker ready."
        )

    # ========================================================
    # CAMERA
    # ========================================================

    def _initialize_camera(self):
        print("[3/5] Opening webcam...")

        self.camera = cv2.VideoCapture(
            CAMERA_DEVICE,
            cv2.CAP_V4L2
        )

        if not self.camera.isOpened():
            raise RuntimeError(
                f"Could not open {CAMERA_DEVICE}"
            )

        # ----------------------------------------------------
        # Camera format
        # ----------------------------------------------------

        fourcc = cv2.VideoWriter_fourcc(
            *CAMERA_FORMAT
        )

        self.camera.set(
            cv2.CAP_PROP_FOURCC,
            fourcc
        )

        self.camera.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            CAMERA_WIDTH
        )

        self.camera.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            CAMERA_HEIGHT
        )

        self.camera.set(
            cv2.CAP_PROP_FPS,
            CAMERA_FPS
        )

        # IMPORTANT:
        #
        # These controls must be applied AFTER OpenCV opens
        # and configures the camera.
        #
        # Otherwise this webcam falls from ~30 FPS to
        # roughly 15-20 FPS.
        self._apply_camera_controls()

        # ----------------------------------------------------
        # Read back actual camera configuration
        # ----------------------------------------------------

        actual_width = int(
            self.camera.get(
                cv2.CAP_PROP_FRAME_WIDTH
            )
        )

        actual_height = int(
            self.camera.get(
                cv2.CAP_PROP_FRAME_HEIGHT
            )
        )

        actual_fps = self.camera.get(
            cv2.CAP_PROP_FPS
        )

        actual_fourcc_value = int(
            self.camera.get(
                cv2.CAP_PROP_FOURCC
            )
        )

        actual_fourcc = "".join(
            chr(
                (
                    actual_fourcc_value
                    >> (8 * i)
                )
                & 0xFF
            )
            for i in range(4)
        )

        print(
            f"      Device: {CAMERA_DEVICE}"
        )

        print(
            f"      Resolution: "
            f"{actual_width}x{actual_height}"
        )

        print(
            f"      FPS: {actual_fps}"
        )

        print(
            f"      Format: {actual_fourcc}"
        )

        # ----------------------------------------------------
        # Validate important settings
        # ----------------------------------------------------

        if (
            actual_width != CAMERA_WIDTH
            or actual_height != CAMERA_HEIGHT
        ):
            raise RuntimeError(
                "Camera did not accept requested "
                f"{CAMERA_WIDTH}x{CAMERA_HEIGHT} "
                "resolution."
            )

        if actual_fourcc != CAMERA_FORMAT:
            print(
                "      WARNING: Camera format is "
                f"{actual_fourcc}, expected "
                f"{CAMERA_FORMAT}"
            )

        if actual_fps < CAMERA_FPS - 1:
            print(
                "      WARNING: Camera reports only "
                f"{actual_fps:.2f} FPS."
            )

    def _apply_camera_controls(self):
        print(
            "      Applying camera controls..."
        )

        command = [
            "v4l2-ctl",

            "-d",
            CAMERA_DEVICE,

            (
                "--set-ctrl="
                f"auto_exposure="
                f"{CAMERA_AUTO_EXPOSURE}"
            ),

            (
                "--set-ctrl="
                f"exposure_time_absolute="
                f"{CAMERA_EXPOSURE}"
            ),

            (
                "--set-ctrl="
                f"gain="
                f"{CAMERA_GAIN}"
            ),
        ]

        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )

        except FileNotFoundError as exc:
            raise RuntimeError(
                "v4l2-ctl is not installed. "
                "Install it with: "
                "sudo apt install v4l-utils"
            ) from exc

        except subprocess.CalledProcessError as exc:
            error = (
                exc.stderr.strip()
                if exc.stderr
                else "Unknown V4L2 error"
            )

            raise RuntimeError(
                "Failed to configure webcam controls: "
                f"{error}"
            ) from exc

        print(
            f"      Auto exposure: "
            f"{CAMERA_AUTO_EXPOSURE}"
        )

        print(
            f"      Exposure: "
            f"{CAMERA_EXPOSURE}"
        )

        print(
            f"      Gain: "
            f"{CAMERA_GAIN}"
        )

    # ========================================================
    # CAMERA WARMUP
    # ========================================================

    def _warmup_camera(self):
        print("[4/5] Warming up webcam...")

        successful_frames = 0

        for _ in range(
            CAMERA_WARMUP_FRAMES
        ):
            success, frame = (
                self.camera.read()
            )

            if (
                success
                and frame is not None
            ):
                successful_frames += 1

        if successful_frames == 0:
            raise RuntimeError(
                "Webcam did not produce any frames "
                "during warmup."
            )

        print(
            f"      Captured "
            f"{successful_frames}/"
            f"{CAMERA_WARMUP_FRAMES} "
            f"warmup frames."
        )

    # ========================================================
    # SELF TEST
    # ========================================================

    def _run_self_test(self):
        """
        Verify the complete camera -> MediaPipe GPU pipeline.

        A hand does not need to be visible.
        """

        print(
            "[5/5] Running pipeline self-test..."
        )

        success, frame = (
            self.camera.read()
        )

        if not success or frame is None:
            raise RuntimeError(
                "Camera self-test failed."
            )

        height, width, channels = (
            frame.shape
        )

        print(
            f"      Test frame: "
            f"{width}x{height}x{channels}"
        )

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb
        )

        inference_start = time.perf_counter()

        result = (
            self.landmarker.detect_for_video(
                mp_image,
                0
            )
        )

        inference_ms = (
            time.perf_counter()
            - inference_start
        ) * 1000

        print(
            "      MediaPipe GPU inference successful."
        )

        print(
            f"      Startup inference: "
            f"{inference_ms:.2f} ms"
        )

        print(
            f"      Hands visible during startup: "
            f"{len(result.hand_landmarks)}"
        )


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def initialize():
    """
    Initialize the hand-mouse runtime.

    Usage from main.py:

        app = initialize()

        try:
            ...
        finally:
            app.shutdown()
    """

    app = HandMouseInit()

    return app.start()