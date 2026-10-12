import cv2
import time

from states import states
from gestures import gestures
from utils import EngineUtils
from camera import exposure_controller

class Engine:
    """
    Main runtime loop.

    Engine responsibilities:

        1. Read camera
        2. Detect hand
        3. Get landmarks
        4. Update states
        5. Check gestures
        6. Run recognized gestures
        7. Repeat

    Engine does NOT know:

        - how states work
        - how gestures work
        - what a click means
        - how cursor movement works
        - gesture priorities
        - mouse button behavior

    Those responsibilities belong elsewhere.
    """

    def __init__(
        self,
        app,
        debug=True
    ):
        self.app = app
        self.debug = debug

        self.states = states
        self.gestures = gestures

        self.running = False

        self.frame_number = 0

        # ----------------------------------------------------
        # Runtime statistics
        #
        # utils.py owns the logic that updates these.
        # ----------------------------------------------------

        self.fps = 0.0
        self.inference_ms = 0.0

        self._fps_frames = 0
        self._fps_start = time.perf_counter()

        self._inference_total = 0.0
        self._inference_count = 0

        # ----------------------------------------------------
        # Utility functions
        # ----------------------------------------------------

        self.utils = EngineUtils(
            self
        )

    # ========================================================
    # MAIN LOOP
    # ========================================================

    def run(self):
        """
        Start the interactive hand-mouse loop.
        """

        print()
        print("========================================")
        print(" Jetson Hand Mouse")
        print("========================================")
        print()

        print("Engine started.")

        if self.debug:
            print(
                "Press Q or ESC to quit."
            )

        print()

        self.running = True

        try:

            while self.running:

                # --------------------------------------------
                # 1. READ CAMERA
                # --------------------------------------------

                frame = self._read_camera()
                self._update_exposure(frame)

                # --------------------------------------------
                # 2. DETECT HAND
                # --------------------------------------------

                detection = self._detect_hand(
                    frame
                )

                # --------------------------------------------
                # 3. GET LANDMARKS
                # --------------------------------------------

                landmarks = self._get_landmarks(
                    detection
                )

                # --------------------------------------------
                # NO HAND
                # --------------------------------------------

                if landmarks is None:

                    self._handle_no_hand(
                        frame
                    )

                    continue

                # --------------------------------------------
                # 4. UPDATE STATES
                # --------------------------------------------

                self._update_states(
                    frame,
                    detection,
                    landmarks
                )

                # --------------------------------------------
                # 5. CHECK GESTURES
                # --------------------------------------------

                ready_gestures = (
                    self._check_gestures()
                )

                # --------------------------------------------
                # 6. RUN GESTURES
                # --------------------------------------------

                self._run_gestures(
                    ready_gestures
                )

                # --------------------------------------------
                # 7. RUNTIME / DEBUG
                # --------------------------------------------

                self.utils.update_stats()

                if self.debug:

                    self.utils.show_debug(
                        frame,
                        detection
                    )

        except KeyboardInterrupt:

            print()
            print(
                "Keyboard interrupt."
            )

        finally:

            self.utils.shutdown()

    # ========================================================
    # ENGINE STEPS
    # ========================================================

    def _read_camera(self):
        """
        Read and prepare one camera frame.
        """

        frame = (
            self.app.read_frame()
        )

        # Mirror camera so hand movement feels natural.
        frame = cv2.flip(
            frame,
            1
        )

        self.frame_number += 1

        return frame

    # --------------------------------------------------------

    def _detect_hand(
        self,
        frame
    ):
        """
        Run MediaPipe hand detection.

        Inference timing is passed to utils.py.
        """

        start = (
            time.perf_counter()
        )

        detection = (
            self.app.detect_hands(
                frame
            )
        )

        inference_ms = (
            time.perf_counter()
            - start
        ) * 1000

        self.utils.record_inference(
            inference_ms
        )

        return detection

    # --------------------------------------------------------

    def _get_landmarks(
        self,
        detection
    ):
        """
        Return the tracked hand landmarks.

        Returns None when no hand is visible.
        """

        if not detection.hand_landmarks:
            return None

        return (
            detection.hand_landmarks[0]
        )

    # --------------------------------------------------------

    def _update_states(
        self,
        frame,
        detection,
        landmarks
    ):
        """
        Give the current hand data to states/.

        states/ owns all hand-state interpretation.
        """

        self.states.update(
            landmarks=landmarks,

            frame=frame,

            detection=detection,

            timestamp=time.monotonic(),

            frame_number=self.frame_number
        )

    # --------------------------------------------------------

    def _check_gestures(self):
        """
        Ask gestures/ which gestures should run.

        gestures/ owns:

            - recognition
            - state sequences
            - priorities
            - simultaneous gestures
            - internal gesture history

        Expected return:

            [
                gesture,
                gesture,
                ...
            ]

        Each returned object must provide:

            gesture.run()
        """

        return self.gestures.update(
            self.states
        )

    # --------------------------------------------------------

    def _run_gestures(
        self,
        ready_gestures
    ):
        """
        Execute every recognized gesture.

        Engine does not care what the gesture does.

        Examples:

            MoveCursor.run()
            LeftDown.run()
            LeftUp.run()
            DoubleClick.run()

        But engine never needs to know those names.
        """

        for gesture in ready_gestures:

            gesture.run()

    # --------------------------------------------------------

    def _handle_no_hand(
        self,
        frame
    ):
        """
        Reset state/gesture tracking when the hand disappears.
        """

        self.states.reset()

        self.gestures.reset()

        self.utils.update_stats()

        if self.debug:

            self.utils.show_debug(
                frame,
                None
            )
    def _update_exposure(self, frame):
        exposure_controller.update(frame)