"""
pynput backend -- the original Jetson / X11 path.

This wraps pynput **exactly as the pre-refactor code did** so the Jetson
behaviour is preserved byte-for-byte:

* relative ``move(dx, dy)`` (rounded, no-op when both are zero)
* stateful, idempotent left button
* left double-click

Additional buttons and scrolling are provided purely to satisfy the shared
:class:`~gestures.backend.base.MouseBackend` contract; they do not change any
existing gesture behaviour.

``pynput`` is imported lazily inside the constructor so that importing this
module (and the whole ``gestures`` package) never requires pynput to be
installed -- which matters on the Wayland target where pynput is absent.
"""

from .base import Button, MouseBackend


class PynputBackend(MouseBackend):
    """The preserved Jetson/X11 backend, built on pynput."""

    name = "pynput"

    def __init__(self):
        try:
            from pynput.mouse import Button as _PButton
            from pynput.mouse import Controller
        except Exception as exc:
            raise RuntimeError(
                "pynput backend requires the 'pynput' package "
                "(pip install pynput) and an X11 session."
            ) from exc

        self._controller = Controller()
        self._pbutton = _PButton

        self._map = {
            Button.LEFT: _PButton.left,
            Button.MIDDLE: _PButton.middle,
            Button.RIGHT: _PButton.right,
        }

        # Buttons currently held by us. Idempotency key.
        self._down = set()

    # ========================================================
    # MOVEMENT
    # ========================================================

    def move_relative(self, dx, dy):
        if self._controller is None:
            return
        dx = int(round(dx))
        dy = int(round(dy))

        if dx == 0 and dy == 0:
            return

        self._controller.move(dx, dy)

    def move_absolute(self, x, y):
        if self._controller is None:
            return
        self._controller.position = (
            int(round(x)),
            int(round(y)),
        )

    # ========================================================
    # BUTTONS
    # ========================================================

    def button_down(self, button):
        if self._controller is None:
            return
        if button in self._down:
            return

        self._controller.press(self._map[button])
        self._down.add(button)

    def button_up(self, button):
        if self._controller is None:
            return
        if button not in self._down:
            return

        self._controller.release(self._map[button])
        self._down.discard(button)

    def is_button_down(self, button):
        return button in self._down

    # ========================================================
    # SCROLL
    # ========================================================

    def scroll(self, dx, dy):
        if self._controller is None:
            return
        if self._controller is not None:
            self._controller.scroll(int(dx), -int(dy))

    # ========================================================
    # LIFECYCLE
    # ========================================================

    def close(self):
        # Release anything we are holding, then drop references.
        # pynput's Controller owns no persistent OS handle we must close.
        if self._controller is None:
            return
        try:
            self.release_all()
        finally:
            self._down.clear()
            self._controller = None
