from .._mouse import mouse


class Gesture:

    name = "left_up"

    priority = 1

    HOLD_FRAMES = 3

    def __init__(self):

        self.open_frames = 0

    # ========================================================
    # UPDATE
    # ========================================================

    def update(
        self,
        states
    ):

        # ---------------------------------------------
        # Nothing to release
        # ---------------------------------------------

        if not mouse.is_left_down():

            self.open_frames = 0

            return False

        # ---------------------------------------------
        # OPEN PALM
        # ---------------------------------------------

        if states.is_active(
            "open_palm"
        ):

            self.open_frames += 1

        else:

            self.open_frames = 0

        # ---------------------------------------------
        # Stable release pose
        # ---------------------------------------------

        if (
            self.open_frames
            >=
            self.HOLD_FRAMES
        ):

            self.open_frames = 0

            return True

        return False

    # ========================================================
    # RUN
    # ========================================================

    def run(self):

        mouse.left_up()

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        self.open_frames = 0