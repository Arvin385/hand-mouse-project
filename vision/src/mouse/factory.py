"""
Backend selection.

Select the mouse backend once at startup (never inside the gesture loop).

Selection rules (per the plan):

* Explicit selection always wins: the ``HANDMOUSE_MOUSE_BACKEND`` environment
  variable (``pynput`` | ``uinput`` | ``libei``) or the ``backend`` argument.
* ``auto`` (default) prefers:

    - KDE Wayland  -> libei, falling back to uinput
    - X11 desktop  -> pynput
    - other        -> libei, falling back to uinput, then pynput

The decision uses the *desktop session type*, not the OS name (Ubuntu can run
Wayland too; Manjaro can run X11), which is what the plan requires.

Any backend that cannot be constructed raises a precise, actionable error. The
factory reports a clear error instead of silently choosing an unsafe
alternative.
"""

import os

from .base import MouseBackend

_ENV_VAR = "HANDMOUSE_MOUSE_BACKEND"

_ALL = ("pynput", "uinput", "libei")


def _import_backend(name):
    from .pynput_backend import PynputBackend
    from .uinput_backend import UinputBackend
    from .libei_backend import LibeiBackend

    return {
        "pynput": PynputBackend,
        "uinput": UinputBackend,
        "libei": LibeiBackend,
    }[name]


def detect_session():
    """
    Best-effort classification of the desktop session.

    Returns one of: ``"wayland"``, ``"x11"``, ``"unknown"``.
    """

    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if session_type == "wayland":
        return "wayland"
    if session_type == "x11":
        return "x11"

    # Fallback heuristics (still not OS-name based).
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"

    return "unknown"


def _preferred_order(session):
    if session == "wayland":
        return ("libei", "uinput")
    if session == "x11":
        return ("pynput", "libei", "uinput")

    return ("libei", "uinput", "pynput")


def create_mouse_backend(backend="auto", **kwargs):
    """
    Construct and return a :class:`MouseBackend`.

    Args:
        backend:
            ``"auto"`` (default) or an explicit backend name
            (``"pynput"`` | ``"uinput"`` | ``"libei"``).
        **kwargs:
            Passed through to the backend constructor (e.g.
            ``connect_timeout`` for libei).

    Raises:
        ValueError: If ``backend`` names an unknown backend.
        RuntimeError: If the selected (or every auto-tried) backend cannot be
            constructed. The message explains exactly what to install/enable.
    """

    order = backend_candidates(backend)
    if len(order) == 1:
        return _import_backend(order[0])(**kwargs)

    # ---- auto selection ----
    session = detect_session()

    attempts = []

    for name in order:
        try:
            instance = _import_backend(name)(**kwargs)
        except Exception as exc:
            attempts.append(f"{name}: {exc}")
            continue

        return instance

    raise RuntimeError(
        "No usable mouse backend could be created "
        f"(session detected as '{session}').\n"
        "Tried:\n  - "
        + "\n  - ".join(attempts)
        + "\n"
        "See vision/WAYLAND-SETUP.md for the one-time setup for each backend."
    )


def backend_candidates(backend="auto"):
    """Shared policy for construction and non-injecting diagnostics."""
    requested = (backend or "auto").strip().lower()
    if requested == "auto":
        requested = os.environ.get(_ENV_VAR, "auto").strip().lower()
    if requested not in (*_ALL, "auto"):
        raise ValueError(f"Unknown mouse backend {requested!r}")
    return _preferred_order(detect_session()) if requested == "auto" else (requested,)
