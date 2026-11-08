import importlib.util
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "vision" / "src"
PACKAGE = "_isolated_gesture_tests"


class States:

    def __init__(self, *active, timestamp=0.0, x=0.0, y=0.0):
        self.active = set(active)
        self.context = SimpleNamespace(
            timestamp=timestamp,
            landmarks=[SimpleNamespace(x=x, y=y) for _ in range(21)],
        )

    def is_active(self, name):
        return name in self.active


class GestureTests(unittest.TestCase):

    def setUp(self):
        # Private package stubs bypass package initializers and all real
        # mouse/backend imports, without replacing application modules.
        package = ModuleType(PACKAGE)
        package.__path__ = []
        gestures = ModuleType(PACKAGE + ".gestures")
        gestures.__path__ = [str(SOURCE / "gestures")]
        states = ModuleType(PACKAGE + ".states")
        states.__path__ = [str(SOURCE / "states")]
        mouse_module = ModuleType(PACKAGE + ".gestures._mouse")
        self.mouse = Mock()
        self.mouse.is_left_down.return_value = False
        mouse_module.mouse = self.mouse
        modules = {
            PACKAGE: package,
            gestures.__name__: gestures,
            states.__name__: states,
            mouse_module.__name__: mouse_module,
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def load(self, relative):
        name = PACKAGE + "." + relative.replace("/", ".")
        spec = importlib.util.spec_from_file_location(
            name, SOURCE / (relative + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def gesture(self, name):
        return self.load("gestures/src/" + name).Gesture()

    def test_pinch_overlap_presses_once_and_does_not_release(self):
        down = self.gesture("left_down")
        up = self.gesture("left_up")
        self.assertFalse(down.update(States("open_palm")))
        for frame in range(down.HOLD_FRAMES):
            state = States("open_palm", "index_pinch", timestamp=0.1)
            ready = down.update(state)
            self.assertEqual(ready, frame == down.HOLD_FRAMES - 1)
            if ready:
                down.run()
        self.mouse.left_down.assert_called_once_with()
        self.mouse.is_left_down.return_value = True
        for _ in range(10):
            self.assertFalse(down.update(state))
            self.assertFalse(up.update(state))
        self.mouse.left_up.assert_not_called()
        for frame in range(up.HOLD_FRAMES):
            ready = up.update(States("open_palm"))
            self.assertEqual(ready, frame == up.HOLD_FRAMES - 1)
            if ready:
                up.run()
        self.mouse.left_up.assert_called_once_with()

    def test_pinch_cannot_arm_press(self):
        down = self.gesture("left_down")
        for _ in range(10):
            self.assertFalse(down.update(States("open_palm", "index_pinch")))
        self.assertFalse(down.armed)

    def test_press_requires_consecutive_pinch_and_times_out(self):
        down = self.gesture("left_down")
        down.update(States("open_palm"))
        down.update(States("index_pinch", timestamp=0.1))
        down.update(States(timestamp=0.2))
        self.assertEqual(down.index_frames, 0)
        self.assertFalse(down.update(States("index_pinch", timestamp=2.0)))
        self.assertFalse(down.armed)
        down.reset()
        self.mouse.left_up.assert_called_once_with()

    def test_pinch_interrupts_release_debounce(self):
        up = self.gesture("left_up")
        self.mouse.is_left_down.return_value = True
        for _ in range(up.HOLD_FRAMES - 1):
            self.assertFalse(up.update(States("open_palm")))
        self.assertFalse(up.update(States("open_palm", "index_pinch")))
        self.assertEqual(up.open_frames, 0)
        for _ in range(up.HOLD_FRAMES - 1):
            self.assertFalse(up.update(States("open_palm")))
        self.assertTrue(up.update(States("open_palm")))

    def test_double_click_after_long_initial_palm_hold(self):
        gesture = self.gesture("double_click")
        for timestamp in (0.0, 1.0, 2.0, 10.0):
            self.assertFalse(gesture.update(States("open_palm", timestamp=timestamp)))
        for frame in range(gesture.HOLD_FRAMES):
            self.assertFalse(gesture.update(States(
                "two_fingers", timestamp=10.1 + frame * 0.1
            )))
        for frame in range(gesture.HOLD_FRAMES):
            ready = gesture.update(States(
                "open_palm", timestamp=10.5 + frame * 0.1
            ))
            self.assertEqual(ready, frame == gesture.HOLD_FRAMES - 1)
            if ready:
                gesture.run()
        self.mouse.double_click.assert_called_once_with()
        self.assertEqual(gesture.stage, "WAIT_OPEN")

    def test_double_click_still_times_out_after_leaving_palm(self):
        for stage in ("WAIT_TWO", "WAIT_OPEN_RETURN"):
            with self.subTest(stage=stage):
                gesture = self.gesture("double_click")
                gesture.update(States("open_palm"))
                if stage == "WAIT_OPEN_RETURN":
                    for frame in range(gesture.HOLD_FRAMES):
                        gesture.update(States("two_fingers", timestamp=0.1 * frame))
                self.assertEqual(gesture.stage, stage)
                self.assertFalse(gesture.update(States("two_fingers", timestamp=3.0)))
                self.assertEqual(gesture.stage, "WAIT_OPEN")

    def test_double_click_disabled_while_dragging(self):
        gesture = self.gesture("double_click")
        gesture.update(States("open_palm"))
        self.mouse.is_left_down.return_value = True
        self.assertFalse(gesture.update(States("two_fingers", timestamp=0.1)))
        self.assertEqual(gesture.stage, "WAIT_OPEN")
        self.mouse.double_click.assert_not_called()

    def test_slow_cursor_motion_accumulates_independently_per_axis(self):
        gesture = self.gesture("move_cursor")
        gesture.SMOOTHING = 1.0
        self.assertFalse(gesture.update(States()))
        self.assertFalse(gesture.update(States(x=0.001, y=-0.0005)))
        self.assertTrue(gesture.update(States(x=0.002, y=-0.001)))
        gesture.run()
        self.mouse.move.assert_called_once_with(0.002 * gesture.GAIN_X, 0)
        self.assertFalse(gesture.update(States(x=0.002, y=-0.001)))
        self.assertTrue(gesture.update(States(x=0.002, y=-0.002)))
        gesture.run()
        self.mouse.move.assert_called_with(0, -0.002 * gesture.GAIN_Y)

    def test_cursor_jitter_does_not_accumulate_path_length(self):
        gesture = self.gesture("move_cursor")
        gesture.SMOOTHING = 1.0
        gesture.update(States())
        for x in (0.001, -0.001, 0.0) * 5:
            self.assertFalse(gesture.update(States(x=x)))
        self.mouse.move.assert_not_called()

    def test_cursor_resets_on_fist_missing_context_and_reset(self):
        for stop in ("fist", "missing", "reset"):
            with self.subTest(stop=stop):
                gesture = self.gesture("move_cursor")
                gesture.update(States())
                gesture.update(States(x=0.001))
                if stop == "reset":
                    gesture.reset()
                else:
                    state = States("fist")
                    if stop == "missing":
                        state.context = None
                    self.assertFalse(gesture.update(state))
                self.assertEqual(gesture.pending_dx, 0)
                self.assertFalse(gesture.update(States(x=0.5, y=0.5)))

    def test_cursor_clamps_tracking_jumps(self):
        gesture = self.gesture("move_cursor")
        gesture.update(States())
        self.assertTrue(gesture.update(States(x=1.0, y=-1.0)))
        gesture.run()
        self.mouse.move.assert_called_once_with(gesture.MAX_STEP, -gesture.MAX_STEP)

    def test_degenerate_pinch_width_is_rejected(self):
        geometry = self.load("states/_geometry")
        for width in (0.0, 0.0000001):
            for tip_distance in (0.0, 0.1):
                with self.subTest(width=width, tip_distance=tip_distance):
                    landmarks = States().context.landmarks
                    landmarks[17].x = width
                    landmarks[8].x = tip_distance
                    self.assertEqual(geometry.pinch_ratio(landmarks), math.inf)
                    self.assertFalse(geometry.thumb_index_pinch(landmarks))

    def test_valid_pinch_threshold(self):
        geometry = self.load("states/_geometry")
        landmarks = States().context.landmarks
        landmarks[17].x = 0.2
        landmarks[8].x = 0.1
        self.assertAlmostEqual(geometry.pinch_ratio(landmarks), 0.5)
        self.assertTrue(geometry.thumb_index_pinch(landmarks))
        landmarks[8].x = 0.11
        self.assertFalse(geometry.thumb_index_pinch(landmarks))


if __name__ == "__main__":
    unittest.main()
