from .._mouse import mouse


class Gesture:

    name = "move_cursor"

    priority = 0

    # ========================================================
    # TUNING
    # ========================================================

    GAIN_X = 3200
    GAIN_Y = 3200

    DEADZONE = 0.0015

    MAX_STEP = 100

    SMOOTHING = 0.55

    # Palm landmarks:
    #
    # 0  wrist
    # 5  index MCP
    # 9  middle MCP
    # 13 ring MCP
    # 17 pinky MCP

    PALM_LANDMARKS = [
        0,
        5,
        9,
        13,
        17
    ]

    def __init__(self):

        self.previous_x = None
        self.previous_y = None

        self.filtered_x = None
        self.filtered_y = None

        self.pending_dx = 0
        self.pending_dy = 0

    # ========================================================
    # UPDATE
    # ========================================================

    def update(
        self,
        states
    ):
        """
        Cursor movement is active whenever the hand is NOT
        recognized as a fist.
        """

        # ---------------------------------------------
        # Fist disables cursor movement
        # ---------------------------------------------

        if states.is_active(
            "fist"
        ):

            self._reset_tracking()

            return False

        context = states.context

        if context is None:

            self._reset_tracking()

            return False

        landmarks = (
            context.landmarks
        )

        # ---------------------------------------------
        # Calculate palm center
        # ---------------------------------------------

        palm_x = sum(
            landmarks[index].x
            for index in self.PALM_LANDMARKS
        ) / len(
            self.PALM_LANDMARKS
        )

        palm_y = sum(
            landmarks[index].y
            for index in self.PALM_LANDMARKS
        ) / len(
            self.PALM_LANDMARKS
        )

        # ---------------------------------------------
        # First tracking frame
        # ---------------------------------------------

        if self.filtered_x is None:

            self.filtered_x = palm_x
            self.filtered_y = palm_y

            self.previous_x = palm_x
            self.previous_y = palm_y

            return False

        # ---------------------------------------------
        # Smooth position
        # ---------------------------------------------

        alpha = self.SMOOTHING

        self.filtered_x = (
            alpha * palm_x
            +
            (1.0 - alpha)
            * self.filtered_x
        )

        self.filtered_y = (
            alpha * palm_y
            +
            (1.0 - alpha)
            * self.filtered_y
        )

        # ---------------------------------------------
        # Relative movement
        # ---------------------------------------------

        dx = (
            self.filtered_x
            -
            self.previous_x
        )

        dy = (
            self.filtered_y
            -
            self.previous_y
        )

        self.previous_x = (
            self.filtered_x
        )

        self.previous_y = (
            self.filtered_y
        )

        # ---------------------------------------------
        # Deadzone
        # ---------------------------------------------

        if abs(dx) < self.DEADZONE:
            dx = 0

        if abs(dy) < self.DEADZONE:
            dy = 0

        # ---------------------------------------------
        # Convert normalized movement → cursor movement
        # ---------------------------------------------

        dx *= self.GAIN_X
        dy *= self.GAIN_Y

        # ---------------------------------------------
        # Protect against tracking jumps
        # ---------------------------------------------

        dx = max(
            -self.MAX_STEP,
            min(
                self.MAX_STEP,
                dx
            )
        )

        dy = max(
            -self.MAX_STEP,
            min(
                self.MAX_STEP,
                dy
            )
        )

        self.pending_dx = dx
        self.pending_dy = dy

        return (
            round(dx) != 0
            or
            round(dy) != 0
        )

    # ========================================================
    # RUN
    # ========================================================

    def run(self):
        """
        Actually move the operating-system cursor.
        """

        mouse.move(
            self.pending_dx,
            self.pending_dy
        )

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):
        self._reset_tracking()

    def _reset_tracking(self):

        self.previous_x = None
        self.previous_y = None

        self.filtered_x = None
        self.filtered_y = None

        self.pending_dx = 0
        self.pending_dy = 0