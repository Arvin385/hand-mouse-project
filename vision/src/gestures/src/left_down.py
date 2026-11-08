from .._mouse import mouse


class Gesture:

    name = "left_down"

    priority = 1

    # Number of consecutive INDEX_PINCH frames required.
    HOLD_FRAMES = 3

    # Maximum time after seeing open palm that INDEX_PINCH
    # may trigger the press.
    TIMEOUT = 1.5

    def __init__(self):

        self.armed = False

        self.armed_time = 0.0

        self.index_frames = 0

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

        # ---------------------------------------------
        # Already dragging / button already down.
        # ---------------------------------------------

        if mouse.is_left_down():

            self.armed = False
            self.index_frames = 0

            return False

        # ---------------------------------------------
        # Unpinched OPEN PALM arms left-down
        # ---------------------------------------------

        if (
            states.is_active("open_palm")
            and not states.is_active("index_pinch")
        ):

            self.armed = True
            self.armed_time = now

            self.index_frames = 0

            return False

        # ---------------------------------------------
        # Not armed yet
        # ---------------------------------------------

        if not self.armed:
            return False

        # ---------------------------------------------
        # Timeout
        # ---------------------------------------------

        if (
            now - self.armed_time
            >
            self.TIMEOUT
        ):

            self.armed = False
            self.index_frames = 0

            return False

        # ---------------------------------------------
        # INDEX PINCH
        # ---------------------------------------------

        if states.is_active(
            "index_pinch"
        ):

            self.index_frames += 1

        else:

            self.index_frames = 0

        # ---------------------------------------------
        # Stable INDEX PINCH reached
        # ---------------------------------------------

        if (
            self.index_frames
            >=
            self.HOLD_FRAMES
        ):

            self.armed = False
            self.index_frames = 0

            return True

        return False

    # ========================================================
    # RUN
    # ========================================================

    def run(self):

        mouse.left_down()

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        self.armed = False
        self.armed_time = 0.0
        self.index_frames = 0

        # Safety:
        # never leave the OS mouse button held if tracking
        # disappears.
        mouse.left_up()