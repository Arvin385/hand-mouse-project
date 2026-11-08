"""
Cross-platform mouse input layer.

A small, stable shared interface (:class:`MouseBackend`) with interchangeable
OS backends, selected once at application startup -- never inside the gesture
loop.

    pynput  -- Jetson / X11          (original behaviour, preserved)
    uinput  -- Wayland fallback      (python-evdev virtual pointer)
    libei   -- Wayland primary       (KDE XDG RemoteDesktop portal)

Public API:

    from mouse import Button, MouseBackend, create_mouse_backend
    from mouse import PynputBackend, UinputBackend, LibeiBackend

Importing this package never constructs a backend and never requires pynput,
evdev, or libei to be installed; those are only loaded when a specific backend
is actually selected.
"""

from .base import Button, MouseBackend
from .factory import create_mouse_backend, detect_session
from .pynput_backend import PynputBackend
from .uinput_backend import UinputBackend
from .libei_backend import LibeiBackend

__all__ = [
    "Button",
    "MouseBackend",
    "create_mouse_backend",
    "detect_session",
    "PynputBackend",
    "UinputBackend",
    "LibeiBackend",
]
