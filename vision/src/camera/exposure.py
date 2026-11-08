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
    CAMERA_EXPOSURE_HARD_MIN,
    CAMERA_EXPOSURE_HARD_MAX,
    CAMERA_GAIN_HARD_MIN,
    CAMERA_GAIN_HARD_MAX,
)


class ExposureController:
    """
    Camera brightness / exposure control.

    Supports three modes so the same build can be tuned live for
    different devices and lighting:

        manual      User drives exposure/gain directly (live sliders).
        software    Camera stays MANUAL; controller slowly steps
                    exposure/gain toward a target brightness.
                    (This is the original Jetson-safe behavior.)
        native      Camera native auto exposure (auto_exposure=3).
                    Works on sensors (e.g. the ASUS laptop webcam)
                    whose manual mode does not brighten usefully.

    Only one mode is active at a time. The engine loop calls
    update(frame) every frame; update() does nothing unless the
    software mode is selected.
    """

    # ========================================================
    # MODES
    # ========================================================

    MODE_MANUAL = "manual"
    MODE_SOFTWARE = "software"
    MODE_NATIVE = "native"

    # UI trackbars expose these in this exact order.
    MODES = (MODE_MANUAL, MODE_SOFTWARE, MODE_NATIVE)

    # V4L2 auto_exposure menu values.
    V4L2_MANUAL = 1
    V4L2_NATIVE_AUTO = 3

    # ========================================================
    # CAMERA
    # ========================================================

    DEVICE = CAMERA_DEVICE

    # These should match the initial settings used by init.py.
    START_EXPOSURE = CAMERA_EXPOSURE
    START_GAIN = CAMERA_GAIN

    # ========================================================
    # SOFTWARE AUTO LIMITS
    # ========================================================

    # exposure_time_absolute uses ~100 us units on the Jetson
    # webcam:
    #
    #   20  = 2 ms
    #   100 = 10 ms
    #   200 = 20 ms
    #
    # Keeping software-auto exposure <= 200 prevents exposure
    # from interfering with the 30 FPS target.
    #
    # NOTE: On sensors where manual exposure does not brighten
    # (e.g. the ASUS laptop webcam), software-auto cannot help;
    # use native mode there instead.

    EXPOSURE_MIN = max(CAMERA_EXPOSURE_MIN, CAMERA_EXPOSURE_HARD_MIN)
    EXPOSURE_MAX = min(CAMERA_EXPOSURE_MAX, CAMERA_EXPOSURE_HARD_MAX)

    GAIN_MIN = max(CAMERA_GAIN_MIN, CAMERA_GAIN_HARD_MIN)
    GAIN_MAX = min(CAMERA_GAIN_MAX, CAMERA_GAIN_HARD_MAX)

    # ========================================================
    # BRIGHTNESS TARGET (software mode)
    # ========================================================

    TARGET_BRIGHTNESS = 115
    BRIGHTNESS_TOLERANCE = 15

    # ========================================================
    # ADJUSTMENT SPEED (software mode)
    # ========================================================

    EXPOSURE_STEP = 10
    GAIN_STEP = 2

    # Check lighting every N frames.
    # At 30 FPS: 10 frames ~= 3 checks / second.
    CHECK_EVERY_FRAMES = 10

    def __init__(self):
        # Default keeps the original Jetson-safe behavior.
        # Use the UI to switch to native mode on the laptop.
        self.mode = self.MODE_SOFTWARE
        self.pending_mode = None

        self.exposure = self.START_EXPOSURE
        self.gain = self.START_GAIN

        self.frame_count = 0
        self.last_brightness = None

    # ========================================================
    # PUBLIC API FOR THE LIVE UI
    # ========================================================

    @property
    def mode_index(self):
        """Index of the current mode in MODES (for a trackbar)."""
        try:
            return self.MODES.index(self.mode)
        except ValueError:
            return 0

    def set_mode(self, mode):
        """
        Switch operating mode.

        manual / software both keep the webcam in MANUAL exposure;
        native switches to the camera's auto exposure.
        """
        if mode not in self.MODES:
            raise ValueError(f"Unknown exposure mode: {mode!r}")
        if mode == self.mode and self.pending_mode is None:
            return True

        # A failed write may still have changed hardware. Keep the last
        # committed mode, but suspend automatic/manual writes until a full
        # transition succeeds, even when retrying the old mode.
        self.pending_mode = mode
        auto = self.V4L2_NATIVE_AUTO if mode == self.MODE_NATIVE else self.V4L2_MANUAL
        if not self._set_control("auto_exposure", auto):
            return False
        if mode != self.MODE_NATIVE:
            exposure, gain = self.exposure, self.gain
            if mode == self.MODE_SOFTWARE:
                exposure = max(self.EXPOSURE_MIN, min(self.EXPOSURE_MAX, exposure))
                gain = max(self.GAIN_MIN, min(self.GAIN_MAX, gain))
            # Native auto can change hardware without changing our cache.
            if not self._set_exposure(exposure, force=True):
                return False
            if not self._set_gain(gain, force=True):
                return False

        self.mode = mode
        self.pending_mode = None
        self.reset()
        return True

    def set_manual(self, exposure=None, gain=None):
        """
        Drive exposure/gain directly (used in manual mode).

        Values are applied only when they actually change.
        """
        if self.mode != self.MODE_MANUAL or self.pending_mode is not None:
            return

        if exposure is not None:
            self._set_exposure(int(exposure))

        if gain is not None:
            self._set_gain(int(gain))

    def set_target_brightness(self, value):
        """Adjust the software-mode brightness target."""
        self.TARGET_BRIGHTNESS = int(value)

    # ========================================================
    # ENGINE LOOP
    # ========================================================

    def update(self, frame):
        """
        Called once for every camera frame.

        Does nothing unless the software mode is active. In
        software mode, every CHECK_EVERY_FRAMES frames we measure
        brightness and make one small adjustment toward the target.
        """
        if self.mode != self.MODE_SOFTWARE or self.pending_mode is not None:
            return

        if frame is None:
            return

        self.frame_count += 1

        if self.frame_count % self.CHECK_EVERY_FRAMES != 0:
            return

        brightness = self._measure_brightness(frame)
        self.last_brightness = brightness

        lower_limit = self.TARGET_BRIGHTNESS - self.BRIGHTNESS_TOLERANCE
        upper_limit = self.TARGET_BRIGHTNESS + self.BRIGHTNESS_TOLERANCE

        if brightness > upper_limit:
            self._darken()
        elif brightness < lower_limit:
            self._brighten()

    # ========================================================
    # BRIGHTNESS MEASUREMENT (software mode)
    # ========================================================

    def _measure_brightness(self, frame):
        """
        Estimate frame brightness.

        We shrink the frame first because we don't need
        full-resolution pixels just to estimate exposure.

        The 60th percentile is more resistant than a normal
        average to one unusually bright/dark part of the image.
        """
        small = cv2.resize(frame, (160, 120))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        return float(np.percentile(gray, 60))

    # ========================================================
    # SOFTWARE AUTO ADJUSTMENT (software mode)
    # ========================================================

    def _darken(self):
        """
        Image is too bright.

        First reduce gain. If gain is already at its minimum,
        reduce exposure time.
        """
        if self.gain > self.GAIN_MIN:
            self._set_gain(max(self.GAIN_MIN, self.gain - self.GAIN_STEP))
            return

        if self.exposure > self.EXPOSURE_MIN:
            self._set_exposure(
                max(self.EXPOSURE_MIN, self.exposure - self.EXPOSURE_STEP)
            )

    def _brighten(self):
        """
        Image is too dark.

        First increase exposure up to the safe limit, then gain.
        This prevents the camera from stretching exposure enough
        to lower the frame rate.
        """
        if self.exposure < self.EXPOSURE_MAX:
            self._set_exposure(
                min(self.EXPOSURE_MAX, self.exposure + self.EXPOSURE_STEP)
            )
            return

        if self.gain < self.GAIN_MAX:
            self._set_gain(
                min(self.GAIN_MAX, self.gain + self.GAIN_STEP)
            )

    # ========================================================
    # CAMERA CONTROLS
    # ========================================================

    def _set_exposure(self, value, force=False):
        """Change exposure, bounded only to hardware limits.

        Software-mode stepping enforces its own tighter caps
        before calling here, so the live manual UI can reach the
        full hardware range for any device/situation.
        """
        value = max(
            CAMERA_EXPOSURE_HARD_MIN,
            min(CAMERA_EXPOSURE_HARD_MAX, value),
        )

        if value == self.exposure and not force:
            return True

        if self._set_control("exposure_time_absolute", value):
            self.exposure = value
            return True
        return False

    def _set_gain(self, value, force=False):
        value = max(
            CAMERA_GAIN_HARD_MIN,
            min(CAMERA_GAIN_HARD_MAX, value),
        )

        if value == self.gain and not force:
            return True

        if self._set_control("gain", value):
            self.gain = value
            return True
        return False

    def _set_control(self, name, value):
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
                timeout=1.0,
            )
            return True
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            print(
                f"Exposure controller: could not set {name}={value}: {exc}"
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
        """Useful for debugging/logging and the live UI."""
        return {
            "mode": self.mode,
                        "pending_mode": self.pending_mode,
            "brightness": self.last_brightness,
            "exposure": self.exposure,
            "gain": self.gain,
            "target": self.TARGET_BRIGHTNESS,
        }
