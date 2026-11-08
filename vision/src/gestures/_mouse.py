"""
Shared mouse facade used internally by gestures.

``engine.py`` does not interact with this object. Gesture code calls only the
methods defined here (``move`` / ``left_down`` / ``left_up`` /
``is_left_down`` / ``double_click`` / ``release_all``) -- the *same* public
API as before this refactor, so the gesture-recognition files are unchanged.

Under the hood this facade delegates to a single OS :class:`MouseBackend`
selected once at startup (see the top-level :mod:`mouse` package):

    * pynput  -- Jetson / X11 (original behaviour, preserved)
    * uinput  -- Wayland fallback (evdev)
    * libei   -- Wayland primary (KDE RemoteDesktop portal)

The backend is constructed eagerly so a misconfiguration fails fast with a
clear, actionable message rather than silently doing nothing.
"""

from mouse import Button, create_mouse_backend


class Mouse:
    """
    Shared mouse interface used internally by gestures.

    A thin, stable facade over the selected :class:`MouseBackend`. The public
    method set is intentionally unchanged from the original implementation so
    that no gesture file needs to change when the backend does.
    """

    def __init__(self):
        # Explicit selection is available via the HANDMOUSE_MOUSE_BACKEND
        # environment variable (pynput | uinput | libei); the factory handles
        # it plus automatic session-based detection.
        self._backend = create_mouse_backend()

        # Backend state is authoritative across pause, disconnect and close.

    # ========================================================
    # BACKEND ACCESS
    # ========================================================

    @property
    def backend(self):
        return self._backend

    @property
    def backend_name(self):
        return self._backend.name

    # ========================================================
    # MOVEMENT
    # ========================================================

    def move(self, dx, dy):
        """
        Move the cursor by a relative amount (logical pixels).

        Safe to call with (0, 0) -- it is a no-op.
        """

        self._backend.move_relative(
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

        if self.is_left_down():
            return

        self._backend.button_down(
            Button.LEFT
        )

    def left_up(self):
        """
        Release left mouse button.

        Safe to call repeatedly.
        """

        if not self.is_left_down():
            return

        self._backend.button_up(
            Button.LEFT
        )

    def is_left_down(self):
        return self._backend.is_button_down(Button.LEFT)

    # ========================================================
    # DOUBLE CLICK
    # ========================================================

    def double_click(self):
        """
        Execute a left-button double click.
        """

        if self.is_left_down():
            return

        self._backend.click(
            Button.LEFT,
            2
        )

    # ========================================================
    # SAFETY / LIFECYCLE
    # ========================================================

    def release_all(self):
        self._backend.release_all()

    def close(self):
        """
        Release backend resources and any held buttons.

        Idempotent. Safe to call from shutdown paths. Never leaves the left
        button logically held.
        """

        try:
            self.release_all()
        except Exception:
            pass

        try:
            self._backend.close()
        except Exception:
            pass


# Shared by every gesture.
mouse = Mouse()
