"""Camera tests use fake controls/trackbars; never access camera hardware."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vision" / "src"))

from camera.exposure import ExposureController
from camera.config import CAMERA_EXPOSURE_HARD_MIN
from utils import EngineUtils


class FakeController(ExposureController):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail_at = None
        self.hardware = {"auto_exposure": 1, "exposure_time_absolute": 200, "gain": 32}

    def _set_control(self, name, value):
        self.calls.append((name, value))
        # Model even a failed command having partially changed hardware.
        self.hardware[name] = value
        return len(self.calls) != self.fail_at


class CameraTests(unittest.TestCase):
    def test_validation_and_noop(self):
        c = FakeController()
        with self.assertRaises(ValueError):
            c.set_mode("bogus")
        self.assertTrue(c.set_mode("software"))
        self.assertEqual(c.calls, [])

    def test_native_return_forces_cached_values(self):
        for mode in ("manual", "software"):
            with self.subTest(mode=mode):
                c = FakeController()
                self.assertTrue(c.set_mode("native"))
                c.hardware.update(exposure_time_absolute=999, gain=100)
                self.assertTrue(c.set_mode(mode))
                self.assertEqual(c.calls[-3:], [
                    ("auto_exposure", 1), ("exposure_time_absolute", 200), ("gain", 32)])
                self.assertEqual(c.mode, mode)
                self.assertIsNone(c.pending_mode)

    def test_failure_at_each_transition_step_is_retryable(self):
        for source, target in (("software", "native"), ("native", "software"),
                               ("native", "manual"), ("manual", "software")):
            for step in range(1, 2 if target == "native" else 4):
                with self.subTest(source=source, target=target, step=step):
                    c = FakeController()
                    c.set_mode(source)
                    c.fail_at = len(c.calls) + step
                    self.assertFalse(c.set_mode(target))
                    self.assertEqual(c.mode, source)
                    self.assertEqual(c.pending_mode, target)
                    calls = list(c.calls)
                    c.update(object())
                    c.set_manual(123, 5)
                    self.assertEqual(c.calls, calls)
                    c.fail_at = None
                    self.assertTrue(c.set_mode(target))
                    self.assertEqual(c.mode, target)
                    self.assertIsNone(c.pending_mode)

    def test_retry_old_mode_after_partial_native_failure(self):
        c = FakeController()
        c.fail_at = 1
        self.assertFalse(c.set_mode("native"))
        self.assertEqual(c.hardware["auto_exposure"], 3)
        c.fail_at = None
        self.assertTrue(c.set_mode("software"))
        self.assertEqual(c.hardware["auto_exposure"], 1)

    def test_software_entry_clamps_and_darken_reaches_gain(self):
        c = FakeController()
        c.set_mode("manual")
        c.set_manual(10000, 128)
        self.assertTrue(c.set_mode("software"))
        self.assertEqual((c.exposure, c.gain), (c.EXPOSURE_MAX, c.GAIN_MAX))
        c.set_mode("manual")
        c.set_manual(0, 0)
        c.set_mode("software")
        self.assertEqual(c.exposure, CAMERA_EXPOSURE_HARD_MIN)
        before = len(c.calls)
        c._darken()
        self.assertEqual(len(c.calls), before)
        c._brighten()
        self.assertEqual(c.exposure, c.EXPOSURE_MIN + c.EXPOSURE_STEP)

    def test_ui_retries_and_does_not_restore_stale_sliders(self):
        c = FakeController()
        c.exposure, c.gain = 80, 4
        sliders = {"Mode": 0, "Exposure": 200, "Gain": 32, "Target": 115}
        ui = EngineUtils(None)
        def get(name, window):
            return sliders[name]
        def put(name, window, value):
            sliders[name] = value
        with patch("utils.exposure_controller", c), \
             patch("utils.cv2.getTrackbarPos", side_effect=get), \
             patch("utils.cv2.setTrackbarPos", side_effect=put):
            c.fail_at = 1
            ui._apply_ui()
            self.assertEqual(c.mode, "software")
            self.assertEqual(sliders["Mode"], 0)
            c.fail_at = None
            ui._apply_ui()
            self.assertEqual(c.mode, "manual")
            self.assertEqual((c.exposure, c.gain), (80, 4))
            self.assertEqual((sliders["Exposure"], sliders["Gain"]), (80, 4))
            sliders["Exposure"] = 90
            ui._apply_ui()
            self.assertEqual(c.exposure, 90)


if __name__ == "__main__":
    unittest.main()
