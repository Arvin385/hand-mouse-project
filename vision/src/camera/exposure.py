import cv2
import numpy as np
import subprocess
from .config import (
    CAMERA_DEVICE,
    CAMERA_EXPOSURE,
    CAMERA_GAIN,
    CAMERA_EXPOSURE_MIN,
    CAMERA_EXPOSURE_MAX,
    CAMERA_GAIN_MIN,
    CAMERA_GAIN_MAX,
)

class ExposureController:
    """
    Software-controlled automatic exposure.

    The webcam itself remains in MANUAL exposure mode so it
    cannot lower the camera frame rate.

    Every few frames we inspect image brightness and slowly
    adjust exposure/gain ourselves.
    """

    # ========================================================
    # CAMERA
    # ========================================================

    DEVICE = "/dev/video0"

    # These should match the initial settings used by init.py.
    START_EXPOSURE = 200
    START_GAIN = 32

    # ========================================================
    # EXPOSURE LIMITS
    # ========================================================

    # exposure_time_absolute uses ~100 us units:
    #
    #   20  = 2 ms
    #   100 = 10 ms
    #   200 = 20 ms
    #
    # Keeping this <= 200 prevents exposure from interfering
    # with our 30 FPS target.

    EXPOSURE_MIN = 20
    EXPOSURE_MAX = 200

    GAIN_MIN = 0
    GAIN_MAX = 63

    # ========================================================
    # BRIGHTNESS TARGET
    # ========================================================

    TARGET_BRIGHTNESS = 115

    # No adjustment while brightness is inside:
    #
    #   100 - 130
    #
    BRIGHTNESS_TOLERANCE = 15

    # ========================================================
    # ADJUSTMENT SPEED
    # ========================================================

    EXPOSURE_STEP = 10
    GAIN_STEP = 2

    # Check lighting every N frames.
    #
    # At 30 FPS:
    #
    #   10 frames ~= 3 checks / second
    #
    CHECK_EVERY_FRAMES = 10

    def __init__(self):
        self.exposure = self.START_EXPOSURE
        self.gain = self.START_GAIN

        self.frame_count = 0

        self.last_brightness = None

    # ========================================================
    # UPDATE
    # ========================================================

    def update(self, frame):
        """
        Called once for every camera frame.

        Most calls return immediately.

        Every CHECK_EVERY_FRAMES frames we measure brightness
        and, if necessary, make one small camera adjustment.
        """

        if frame is None:
            return

        self.frame_count += 1

        if (
            self.frame_count
            %
            self.CHECK_EVERY_FRAMES
            != 0
        ):
            return

        brightness = self._measure_brightness(
            frame
        )

        self.last_brightness = brightness

        lower_limit = (
            self.TARGET_BRIGHTNESS
            -
            self.BRIGHTNESS_TOLERANCE
        )

        upper_limit = (
            self.TARGET_BRIGHTNESS
            +
            self.BRIGHTNESS_TOLERANCE
        )

        # ----------------------------------------------------
        # TOO BRIGHT
        # ----------------------------------------------------

        if brightness > upper_limit:

            self._darken()

        # ----------------------------------------------------
        # TOO DARK
        # ----------------------------------------------------

        elif brightness < lower_limit:

            self._brighten()

    # ========================================================
    # BRIGHTNESS MEASUREMENT
    # ========================================================

    def _measure_brightness(self, frame):
        """
        Estimate frame brightness.

        We shrink the frame first because we don't need
        full-resolution pixels just to estimate exposure.

        The 60th percentile is more resistant than a normal
        average to one unusually bright/dark part of the image.
        """

        small = cv2.resize(
            frame,
            (160, 120)
        )

        gray = cv2.cvtColor(
            small,
            cv2.COLOR_BGR2GRAY
        )

        return float(
            np.percentile(
                gray,
                60
            )
        )

    # ========================================================
    # DARKEN IMAGE
    # ========================================================

    def _darken(self):
        """
        Image is too bright.

        First reduce gain.

        If gain has already reached its minimum, reduce
        exposure time.
        """

        if self.gain > self.GAIN_MIN:

            new_gain = max(
                self.GAIN_MIN,
                self.gain - self.GAIN_STEP
            )

            self._set_gain(
                new_gain
            )

            return

        if self.exposure > self.EXPOSURE_MIN:

            new_exposure = max(
                self.EXPOSURE_MIN,
                self.exposure
                -
                self.EXPOSURE_STEP
            )

            self._set_exposure(
                new_exposure
            )

    # ========================================================
    # BRIGHTEN IMAGE
    # ========================================================

    def _brighten(self):
        """
        Image is too dark.

        First increase exposure up to our safe 20 ms limit.

        After that, increase gain.

        This prevents the camera from stretching exposure
        enough to lower frame rate.
        """

        if self.exposure < self.EXPOSURE_MAX:

            new_exposure = min(
                self.EXPOSURE_MAX,
                self.exposure
                +
                self.EXPOSURE_STEP
            )

            self._set_exposure(
                new_exposure
            )

            return

        if self.gain < self.GAIN_MAX:

            new_gain = min(
                self.GAIN_MAX,
                self.gain
                +
                self.GAIN_STEP
            )

            self._set_gain(
                new_gain
            )

    # ========================================================
    # CAMERA CONTROLS
    # ========================================================

    def _set_exposure(
        self,
        value
    ):
        """
        Change exposure while keeping webcam auto exposure OFF.
        """

        if value == self.exposure:
            return

        success = self._set_control(
            "exposure_time_absolute",
            value
        )

        if success:
            self.exposure = value

    def _set_gain(
        self,
        value
    ):
        if value == self.gain:
            return

        success = self._set_control(
            "gain",
            value
        )

        if success:
            self.gain = value

    def _set_control(
        self,
        name,
        value
    ):
        """
        Apply one V4L2 camera control.

        Returns True only when v4l2-ctl succeeds.
        """

        try:

            subprocess.run(
                [
                    "v4l2-ctl",
                    "-d",
                    self.DEVICE,
                    f"--set-ctrl={name}={value}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0
            )

            return True

        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError
        ) as exc:

            print(
                f"Exposure controller: "
                f"could not set {name}={value}: "
                f"{exc}"
            )

            return False

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):
        """
        Reset only the controller's timing.

        Camera exposure itself is left unchanged.
        """

        self.frame_count = 0
        self.last_brightness = None

    # ========================================================
    # DEBUG
    # ========================================================

    def status(self):
        """
        Useful for debugging/logging.
        """

        return {
            "brightness": self.last_brightness,
            "exposure": self.exposure,
            "gain": self.gain,
        }