from .._mouse import mouse


class Gesture:

    name = "double_click"

    priority = 1

    HOLD_FRAMES = 3

    TIMEOUT = 1.5

    def __init__(self):

        self.stage = "WAIT_OPEN"

        self.two_finger_frames = 0
        self.open_frames = 0

        self.stage_time = 0.0

    # ========================================================
    # UPDATE
    # ========================================================

    def update(
        self,
        states
    ):

        context = states.context

        if context is None:
            return False

        now = (
            context.timestamp
        )

        # Do not double-click while dragging.
        if mouse.is_left_down():

            self._clear()

            return False

        # ---------------------------------------------
        # STAGE 1
        #
        # Wait for open palm.
        # ---------------------------------------------

        if self.stage == "WAIT_OPEN":

            if states.is_active(
                "open_palm"
            ):

                self.stage = (
                    "WAIT_TWO"
                )

                self.stage_time = now

            return False

        # Holding the initial palm keeps the sequence armed.
        if (
            self.stage == "WAIT_TWO"
            and states.is_active("open_palm")
        ):

            self.stage_time = now
            self.two_finger_frames = 0

            return False

        # ---------------------------------------------
        # Sequence timeout
        # ---------------------------------------------

        if (
            now - self.stage_time
            >
            self.TIMEOUT
        ):

            self._clear()

            return False

        # ---------------------------------------------
        # STAGE 2
        #
        # Wait for stable two-finger pose.
        # ---------------------------------------------

        if self.stage == "WAIT_TWO":

            if states.is_active(
                "two_fingers"
            ):

                self.two_finger_frames += 1

            else:

                self.two_finger_frames = 0

            if (
                self.two_finger_frames
                >=
                self.HOLD_FRAMES
            ):

                self.stage = (
                    "WAIT_OPEN_RETURN"
                )

                self.stage_time = now

                self.open_frames = 0

            return False

        # ---------------------------------------------
        # STAGE 3
        #
        # Wait for open palm again.
        # ---------------------------------------------

        if (
            self.stage
            ==
            "WAIT_OPEN_RETURN"
        ):

            if states.is_active(
                "open_palm"
            ):

                self.open_frames += 1

            else:

                self.open_frames = 0

            if (
                self.open_frames
                >=
                self.HOLD_FRAMES
            ):

                self._clear()

                return True

        return False

    # ========================================================
    # RUN
    # ========================================================

    def run(self):

        mouse.double_click()

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        self._clear()

    def _clear(self):

        self.stage = "WAIT_OPEN"

        self.two_finger_frames = 0
        self.open_frames = 0

        self.stage_time = 0.0