"""
Best-effort display geometry helpers.

Used to size the uinput ABS coordinate range and to normalize/clamp absolute
coordinates under KDE fractional scaling.

Everything here is best-effort and must never raise: when the session cannot
be queried (headless, missing bindings, sandbox), sensible defaults are
returned so the input backend still works (relative motion does not depend on
these values).
"""

_DEFAULT = (1920, 1080)


def _qt_app():
    """
    Return a Qt application instance (creating one if needed) or None.

    Lazy-imported so Qt is only touched when actually available.
    """

    try:
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return None

    app = QApplication.instance()
    if app is None:
        try:
            app = QApplication([])
        except Exception:
            return None
    return app


def logical_screen_size(default=_DEFAULT):
    """
    Return the logical (fractional-scaled) primary output size in pixels.

    On KDE the logical size accounts for fractional scaling, which is exactly
    the coordinate space a cursor position lives in. Falls back to ``default``
    when it cannot be determined.
    """

    app = _qt_app()
    if app is not None:
        try:
            from PyQt5.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.geometry()
                width = geo.width()
                height = geo.height()
                if width > 0 and height > 0:
                    return (int(width), int(height))
        except Exception:
            pass

    return tuple(default)


def current_cursor_position(default=(0, 0)):
    """
    Best-effort current pointer position in logical coordinates.

    Only used to anchor the first absolute move; the input backend still
    works without it (relative motion is independent of this).
    """

    app = _qt_app()
    if app is not None:
        try:
            from PyQt5.QtGui import QCursor
            pos = QCursor.pos()
            return (int(pos.x()), int(pos.y()))
        except Exception:
            pass

    return tuple(default)
