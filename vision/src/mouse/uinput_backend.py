"""
uinput backend -- the sanctioned Linux Wayland fallback (python-evdev).

Creates a single *persistent* virtual pointer device and injects:

* relative motion (EV_REL REL_X/REL_Y)  -- matches the existing gesture mapping
* buttons (EV_KEY BTN_*)
* wheel / horizontal scroll (EV_REL)

The device intentionally declares **no EV_ABS axes**. libinput classifies a
device that has both ABS_X/ABS_Y *and* REL_X/REL_Y as a "combo" pointer and
starts it in absolute mode, silently discarding relative events -- verified
on the Zenbook (KDE/Wayland): with ABS axes declared, REL motion moved
nothing. Declaring REL only matches the physical touchpad and libinput then
handles our motion normally. Absolute positioning therefore is not available
on this backend; ``move_absolute`` keeps the base-class default (raises),
which is fine because every gesture uses relative motion.

No root is needed at *runtime*. The only setup is one-time:

    sudo modprobe uinput
    sudo usermod -aG input $USER    # then log out/in

This backend is used when the primary libei/KDE-portal path is unavailable
(e.g. ``xdg-desktop-portal-kde`` is not installed), which is the current state
on the target Zenbook. See ``vision/WAYLAND-SETUP.md``.

``evdev`` is imported lazily inside the constructor so the module imports
cleanly even where evdev (or the ``/dev/uinput`` node) is missing.
"""

import os

from .base import Button, MouseBackend

_UINPUT_NODE = "/dev/uinput"

_DEVICE_NAME = "hand-mouse-uinput"


class UinputBackend(MouseBackend):
    """Linux uinput virtual pointer, backed by python-evdev."""

    name = "uinput"

    def __init__(self):
        if not os.path.exists(_UINPUT_NODE):
            raise RuntimeError(
                "uinput backend unavailable: /dev/uinput does not exist.\n"
                "  One-time setup (no root at runtime):\n"
                "      sudo modprobe uinput\n"
                "      sudo usermod -aG input $USER   # log out/in\n"
                "Or enable the KDE portal and use the libei backend instead "
                "(see vision/WAYLAND-SETUP.md)."
            )

        try:
            from evdev import UInput, ecodes
        except Exception as exc:
            raise RuntimeError(
                "uinput backend requires the 'evdev' package "
                "(pip install evdev)."
            ) from exc

        self._ecodes = ecodes

        capabilities = {
            # Buttons are declared here (EV_KEY); UInput has no separate
            # ``buttons`` positional argument.
            ecodes.EV_KEY: [
                ecodes.BTN_LEFT,
                ecodes.BTN_MIDDLE,
                ecodes.BTN_RIGHT,
            ],
            # REL only -- see module docstring: declaring EV_ABS alongside
            # EV_REL makes libinput treat this as a combo device and drop
            # every relative event under Wayland.
            ecodes.EV_REL: {
                ecodes.REL_X: 0,
                ecodes.REL_Y: 0,
                ecodes.REL_WHEEL: 0,
                ecodes.REL_HWHEEL: 0,
            },
        }

        try:
            self._device = UInput(
                capabilities,
                name=_DEVICE_NAME,
                vendor=0x1234,
                product=0x5678,
                version=0x0001,
            )
        except PermissionError as exc:
            raise RuntimeError(
                "Could not open /dev/uinput (permission denied). "
                "Add your user to the 'input' group: "
                "sudo usermod -aG input $USER, then log out/in."
            ) from exc

        self._button_code = {
            Button.LEFT: ecodes.BTN_LEFT,
            Button.MIDDLE: ecodes.BTN_MIDDLE,
            Button.RIGHT: ecodes.BTN_RIGHT,
        }

        self._down = set()

    # ========================================================
    # INTERNAL
    # ========================================================

    def _sync(self):
        self._device.syn()

    # ========================================================
    # MOVEMENT
    # ========================================================

    def move_relative(self, dx, dy):
        if self._device is None:
            return
        dx = int(round(dx))
        dy = int(round(dy))

        if dx == 0 and dy == 0:
            return

        ec = self._ecodes
        self._device.write(ec.EV_REL, ec.REL_X, dx)
        self._device.write(ec.EV_REL, ec.REL_Y, dy)
        self._sync()

    # move_absolute is intentionally not implemented -- see module
    # docstring (combo-device behaviour makes absolute injection unusable
    # together with relative motion on this backend).

    # ========================================================
    # BUTTONS
    # ========================================================

    def button_down(self, button):
        if self._device is None:
            return
        if button in self._down:
            return

        self._device.write(
            self._ecodes.EV_KEY,
            self._button_code[button],
            1,
        )
        self._sync()
        self._down.add(button)

    def button_up(self, button):
        if self._device is None:
            return
        if button not in self._down:
            return

        self._device.write(
            self._ecodes.EV_KEY,
            self._button_code[button],
            0,
        )
        self._sync()
        self._down.discard(button)

    def is_button_down(self, button):
        return button in self._down

    # ========================================================
    # SCROLL
    # ========================================================

    def scroll(self, dx, dy):
        if self._device is None:
            return
        ec = self._ecodes

        if dy:
            self._device.write(ec.EV_REL, ec.REL_WHEEL, -int(dy))
            self._sync()

        if dx and hasattr(ec, "REL_HWHEEL"):
            self._device.write(ec.EV_REL, ec.REL_HWHEEL, int(dx))
            self._sync()

    # ========================================================
    # LIFECYCLE
    # ========================================================

    def close(self):
        # Never leave a button logically held.
        if self._device is None:
            return
        try:
            self.release_all()
        finally:
            try:
                self._device.close()
            finally:
                self._device = None
                self._down.clear()
