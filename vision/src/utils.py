import cv2
import time

from camera import exposure_controller
from camera.exposure import ExposureController
from camera.config import (
    CAMERA_EXPOSURE_HARD_MAX,
    CAMERA_GAIN_HARD_MAX,
)


class EngineUtils:
    """
    Runtime utilities used by engine.py.

    This keeps bookkeeping, debugging, shutdown logic,
    and other support functions out of the main engine.
    """

    WINDOW = "Jetson Hand Mouse"

    def __init__(
        self,
        engine
    ):
        self.engine = engine

        # Live settings UI state.
        self._ui_ready = False

    # ========================================================
    # LIVE SETTINGS UI (trackbars on the debug window)
    # ========================================================

    def _init_ui(self):
        """
        Create live-adjustable sliders for camera tuning.

        OpenCV highgui has no editable text field, so numeric
        trackbars are used; they update the camera the moment
        you move them.

        Mode trackbar maps to ExposureController.MODES:
            0 manual    - sliders drive exposure/gain directly
            1 software  - controller auto-brightens (Jetson-safe)
            2 native    - camera native auto exposure (laptop)
        """
        status = exposure_controller.status()

        cv2.createTrackbar(
            "Mode",
            self.WINDOW,
            exposure_controller.mode_index,
            len(ExposureController.MODES) - 1,
            lambda value: None,
        )

        cv2.createTrackbar(
            "Exposure",
            self.WINDOW,
            int(status["exposure"]),
            CAMERA_EXPOSURE_HARD_MAX,
            lambda value: None,
        )

        cv2.createTrackbar(
            "Gain",
            self.WINDOW,
            int(status["gain"]),
            CAMERA_GAIN_HARD_MAX,
            lambda value: None,
        )

        cv2.createTrackbar(
            "Target",
            self.WINDOW,
            int(status["target"]),
            255,
            lambda value: None,
        )

        self._ui_ready = True

    def _apply_ui(self):
        """
        Read slider positions and push them to the controller.

        The controller only issues v4l2-ctl writes when a value
        actually changes, so calling this every frame is cheap.
        """
        mode_index = cv2.getTrackbarPos("Mode", self.WINDOW)
        mode_index = max(
            0,
            min(len(ExposureController.MODES) - 1, mode_index),
        )

        mode = ExposureController.MODES[mode_index]
        previous_mode = exposure_controller.mode
        was_pending = exposure_controller.pending_mode is not None
        if not exposure_controller.set_mode(mode):
            # Leave the requested trackbar selection intact for next-frame retry.
            return

        if mode == ExposureController.MODE_MANUAL and (
            previous_mode != mode or was_pending
        ):
            # Software may have evolved the cache while sliders were inactive.
            # Enter manual with current values, not stale slider positions.
            status = exposure_controller.status()
            cv2.setTrackbarPos("Exposure", self.WINDOW, int(status["exposure"]))
            cv2.setTrackbarPos("Gain", self.WINDOW, int(status["gain"]))

        if mode == ExposureController.MODE_MANUAL:
            exposure = cv2.getTrackbarPos("Exposure", self.WINDOW)
            gain = cv2.getTrackbarPos("Gain", self.WINDOW)
            exposure_controller.set_manual(exposure, gain)

        elif mode == ExposureController.MODE_SOFTWARE:
            exposure_controller.set_target_brightness(
                cv2.getTrackbarPos("Target", self.WINDOW)
            )

        # native mode: the camera owns exposure; sliders ignored.

    # ========================================================
    # INFERENCE STATISTICS
    # ========================================================

    def record_inference(
        self,
        milliseconds
    ):
        """
        Record one MediaPipe inference duration.
        """

        self.engine._inference_total += (
            milliseconds
        )

        self.engine._inference_count += 1

    # ========================================================
    # RUNTIME STATISTICS
    # ========================================================

    def update_stats(self):
        """
        Update FPS and average MediaPipe inference time.
        """

        self.engine._fps_frames += 1

        elapsed = (
            time.perf_counter()
            -
            self.engine._fps_start
        )

        if elapsed < 1.0:
            return

        self.engine.fps = (
            self.engine._fps_frames
            /
            elapsed
        )

        if (
            self.engine._inference_count
            > 0
        ):

            self.engine.inference_ms = (
                self.engine._inference_total
                /
                self.engine._inference_count
            )

        self.engine._fps_frames = 0

        self.engine._fps_start = (
            time.perf_counter()
        )

        self.engine._inference_total = 0.0

        self.engine._inference_count = 0

    # ========================================================
    # DEBUG WINDOW
    # ========================================================

    def show_debug(
        self,
        frame,
        detection
    ):
        """
        Display runtime information.

        State information shown here is debugging only.
        It has no effect on engine behavior.
        """

        # ----------------------------------------------------
        # FPS
        # ----------------------------------------------------

        cv2.putText(
            frame,
            f"FPS: {self.engine.fps:.1f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        # ----------------------------------------------------
        # GPU inference
        # ----------------------------------------------------

        cv2.putText(
            frame,
            (
                f"GPU: "
                f"{self.engine.inference_ms:.1f} ms"
            ),
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        # ----------------------------------------------------
        # Hand visibility
        # ----------------------------------------------------

        hand_visible = (
            detection is not None
            and
            bool(
                detection.hand_landmarks
            )
        )

        cv2.putText(
            frame,
            (
                "Hand: "
                +
                (
                    "YES"
                    if hand_visible
                    else "NO"
                )
            ),
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        # ----------------------------------------------------
        # Active states
        #
        # Purely informational.
        # ----------------------------------------------------

        active_states = []

        try:

            active_states = (
                self.engine.states.active()
            )

        except AttributeError:

            pass

        if active_states:

            cv2.putText(
                frame,
                (
                    "States: "
                    +
                    ", ".join(
                        active_states
                    )
                ),
                (10, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 255, 0),
                1
            )

        # ----------------------------------------------------
        # Current camera settings (live)
        # ----------------------------------------------------

        status = exposure_controller.status()

        brightness = status["brightness"]
        brightness_text = (
            "n/a" if brightness is None else f"{brightness:.0f}"
        )

        cv2.putText(
            frame,
            (
                f"Cam: {status['mode']} pending={status['pending_mode']} "
                f"exp={status['exposure']} "
                f"gain={status['gain']} "
                f"bri={brightness_text}"
            ),
            (10, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (0, 255, 0),
            1
        )

        # ----------------------------------------------------
        # Display
        # ----------------------------------------------------

        cv2.imshow(
            "Jetson Hand Mouse",
            frame
        )

        # Trackbars need an existing window, so create them
        # after the first imshow, then keep them authoritative.
        try:
            if not self._ui_ready:
                self._init_ui()
            self._apply_ui()
        except Exception as exc:
            print(f"Camera settings UI unavailable: {exc}")
            self._ui_ready = False

        key = (
            cv2.waitKey(1)
            &
            0xFF
        )

        if (
            key == ord("q")
            or
            key == 27
        ):

            self.stop()

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):
        """
        Stop the engine loop.
        """

        self.engine.running = False

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def shutdown(self):
        """
        Shut down the engine safely.

        init.py still owns MediaPipe and the camera,
        so those resources are not released here.
        """

        self.engine.running = False

        # Give gestures an opportunity to release things such
        # as a held mouse button.
        try:

            self.engine.gestures.reset()

        except Exception as exc:

            print(
                f"Gesture cleanup warning: {exc}"
            )

        if self.engine.debug:

            cv2.destroyAllWindows()

        print()
        print(
            "Engine stopped."
        )