from pynput.mouse import Button, Controller


class Mouse:
    """
    Shared mouse interface used internally by gestures.

    engine.py does not interact with this object.
    """

    def __init__(self):
        self._controller = Controller()

        self._left_down = False

    # ========================================================
    # MOVEMENT
    # ========================================================

    def move(
        self,
        dx,
        dy
    ):
        dx = int(
            round(dx)
        )

        dy = int(
            round(dy)
        )

        if (
            dx == 0
            and
            dy == 0
        ):
            return

        self._controller.move(
            dx,
            dy
        )

    # ========================================================
    # LEFT BUTTON
    # ========================================================

    def left_down(self):
        """
        Hold left mouse button.

        Safe to call repeatedly.
        """

        if self._left_down:
            return

        self._controller.press(
            Button.left
        )

        self._left_down = True

    def left_up(self):
        """
        Release left mouse button.

        Safe to call repeatedly.
        """

        if not self._left_down:
            return

        self._controller.release(
            Button.left
        )

        self._left_down = False

    def is_left_down(self):
        return self._left_down

    # ========================================================
    # DOUBLE CLICK
    # ========================================================

    def double_click(self):
        """
        Execute a left-button double click.
        """

        if self._left_down:
            return

        self._controller.click(
            Button.left,
            2
        )

    # ========================================================
    # SAFETY
    # ========================================================

    def release_all(self):
        self.left_up()


# Shared by every gesture.
mouse = Mouse()