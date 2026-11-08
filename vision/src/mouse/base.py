"""
Shared mouse backend contract.

Every OS-specific backend implements :class:`MouseBackend`. Gesture code never
touches a concrete backend directly; it talks to the ``Mouse`` facade in
``gestures/_mouse.py``, which delegates to a single backend selected once at
startup (see :mod:`gestures.backend.factory`).

This keeps platform details (pynput / uinput / libei) completely out of the
gesture-recognition code and the engine loop, while preserving the invariant::

    LANDMARKS -> STATES -> GESTURES -> Gesture.run() -> ACTION

Coordinates are logical (fractional-scaled) screen pixels. ``move_relative``
uses the existing relative mapping (normalised delta * GAIN); ``move_absolute``
positions the pointer directly in logical coordinates.

The contract is intentionally small and stable so a new backend only has to
implement the abstract methods.
"""

from abc import ABC, abstractmethod
from enum import Enum


class Button(Enum):
    """
    Normalized mouse button.

    Independent of any OS / evdev / wayland button codes. Backends map this
    to their own representation internally.
    """

    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


class MouseBackend(ABC):
    """
    Common input-control interface shared by all OS backends.

    Movement
        move_relative(dx, dy)   -- abstract, required
        move_absolute(x, y)     -- optional, default raises
    Buttons
        button_down / button_up / is_button_down  -- abstract, required
        click(button, count)    -- provided
    Scroll
        scroll(dx, dy)          -- optional, default no-op
    Lifecycle
        release_all()           -- provided
        close()                 -- abstract, required
    """

    #: Human-readable backend identifier (used in logs/errors).
    name = "base"

    # ========================================================
    # MOVEMENT
    # ========================================================

    @abstractmethod
    def move_relative(self, dx, dy) -> None:
        """Move the pointer by a relative amount (logical pixels)."""

    def move_absolute(self, x, y) -> None:
        """
        Position the pointer at an absolute logical coordinate.

        Optional. Backends that cannot position the cursor absolutely keep the
        default, which fails loudly instead of silently misbehaving.
        """

        raise NotImplementedError(
            f"{self.name}: move_absolute() is not supported"
        )

    # ========================================================
    # BUTTONS
    # ========================================================

    @abstractmethod
    def button_down(self, button) -> None:
        """Press ``button``. Must be idempotent (safe to call repeatedly)."""

    @abstractmethod
    def button_up(self, button) -> None:
        """Release ``button``. Must be idempotent (safe to call repeatedly)."""

    @abstractmethod
    def is_button_down(self, button) -> bool:
        """Return True if ``button`` is logically held by this backend."""

    def click(self, button, count=1) -> None:
        """Press and release ``button`` ``count`` times (default 1)."""

        for _ in range(max(1, int(count))):
            self.button_down(button)
            self.button_up(button)

    # ========================================================
    # SCROLL
    # ========================================================

    def scroll(self, dx, dy) -> None:
        """
        Scroll.

        ``dx``/``dy`` are logical steps (dy positive = down on a typical
        wheel). Optional: the default is a no-op so existing backends that
        predate scrolling keep working.
        """

    # ========================================================
    # LIFECYCLE
    # ========================================================

    def release_all(self) -> None:
        """Release every held button. Safe to call repeatedly."""

        for button in Button:
            self.button_up(button)

    @abstractmethod
    def close(self) -> None:
        """
        Release resources and release any held buttons.

        Must be idempotent and must never leave a button logically pressed.
        """
