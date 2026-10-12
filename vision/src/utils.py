import cv2
import time


class EngineUtils:
    """
    Runtime utilities used by engine.py.

    This keeps bookkeeping, debugging, shutdown logic,
    and other support functions out of the main engine.
    """

    def __init__(
        self,
        engine
    ):
        self.engine = engine

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
        # Display
        # ----------------------------------------------------

        cv2.imshow(
            "Jetson Hand Mouse",
            frame
        )

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