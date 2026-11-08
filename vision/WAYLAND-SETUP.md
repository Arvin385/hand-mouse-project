# Manjaro / KDE Wayland — Setup Guide

Target: **ASUS Zenbook 14** — Manjaro Linux, KDE Plasma 6, Wayland
Also applies to any KDE/Wayland box, and to the Jetson (X11) path.

This project uses a **shared mouse-backend interface** (`vision/src/mouse/`)
with three interchangeable backends, selected **once at startup**:

| Backend  | Used for                        | Needs (one-time)                                        |
|----------|---------------------------------|---------------------------------------------------------|
| `pynput` | Jetson / X11 (original)         | `pynput` + an X11 session                               |
| `uinput` | Wayland (fallback, runnable)    | `python-evdev` + `/dev/uinput` + `input` group          |
| `libei`  | Wayland (primary, KDE portal)   | `xdg-desktop-portal-kde` + portal running + permission  |

Selection order (`auto`) is chosen by the **session type**, not the OS name:

- `wayland` → `libei` → `uinput` (never silently falls back to the X11-only `pynput`)
- `x11`     → `pynput` → `libei` → `uinput`

Override it explicitly with the `HANDMOUSE_MOUSE_BACKEND` env var, e.g.:

```bash
HANDMOUSE_MOUSE_BACKEND=uinput python main.py
```

---

## 0. Verify what you have

```bash
echo "$XDG_SESSION_TYPE"          # wayland  (KDE Plasma 6)
ls -l /usr/lib/libei.so*          # libei (present on the target)
command -v xdg-desktop-portal     # portal (NOT present by default)
ls -l /dev/uinput                 # uinput node (only after `modprobe uinput`)
lsmod | grep uinput               # uinput kernel module (module is present)
```

Run the standalone input test (no camera, no MediaPipe, no gesture app):

```bash
cd vision/src
python test_mouse_backend.py          # policy only; no constructors or input
python test_mouse_backend.py --live   # + a tiny real move and click
```

Default mode only reports the shared factory selection policy; exit 0 does
not establish backend availability. It never constructs a backend, prompts for
portal permissions, or injects input. `--backend NAME` overrides the environment;
otherwise `HANDMOUSE_MOUSE_BACKEND` applies, just as in the application.

**Only `--live` constructs a real backend and injects movement, clicks and
scrolling.** Run it over a safe desktop area. Fake-only regression tests:

```bash
python -m unittest discover -s tests -p test_mouse.py -v
```

---

## Option A — uinput backend (recommended to start; works right now)

This is the sanctioned Wayland fallback and the path that will actually run on
the Zenbook today.

One-time setup (no root at *runtime*):

```bash
# 1) Provide the evdev Python package (pick one):
sudo pacman -S python-evdev          # or:  pip install evdev

# 2) Load the uinput module (the .ko is present on this kernel):
sudo modprobe uinput
ls -l /dev/uinput                     # node must now exist

# 3) Let your user write to it (node is root:input):
sudo usermod -aG input "$USER"
#    log out and back in for the group change to take effect
```

Then verify:

```bash
cd vision/src
python test_mouse_backend.py --backend uinput  # policy only
python test_mouse_backend.py --live     # expect a small cursor nudge + click
```

> Make `modprobe uinput` persistent (so it survives reboots) if you do not want
> to run it manually each boot, e.g. a small udev/systemd rule or a one-liner
> in your session autostart.

The backend uses **relative** motion (exactly the existing gesture mapping) and
supports buttons and wheel scroll. It deliberately declares no `EV_ABS` axes:
libinput treats a device with both ABS and REL axes as a "combo" pointer and
silently drops relative events under Wayland (verified on the Zenbook). Absolute
positioning is therefore unavailable on this backend -- which is fine, every
gesture uses relative motion. It never requires running the application as root.

---

## Option B — libei backend (KDE primary, via the XDG RemoteDesktop portal)

This is the plan's primary approach. It establishes **one persistent**
emulated-input session (no per-event portal calls) and injects relative/absolute
motion, buttons and scroll through a non-blocking dispatch thread.

One-time setup:

```bash
# Portal + KDE implementation (the RemoteDesktop "remote-input" provider):
sudo pacman -S xdg-desktop-portal xdg-desktop-portal-kde

# The Python side needs PyGObject (python-gi). Already present on the target:
python3 -c "import gi; gi.require_version('Gio','2.0'); from gi.repository import Gio"

# libei is already installed on the target (libei.so.1); if not:
#   sudo pacman -S libei
```

Make sure you are logged into a **KDE Wayland** session (not X11) and that
KWin has emulated input enabled. On first run KDE will prompt you to grant the
**remote-input** permission — approve it.

Then verify:

```bash
cd vision/src
python test_mouse_backend.py --backend libei   # policy only
python test_mouse_backend.py --live
```

If `libei` reports the portal is not running, the portal packages above are not
installed or the session is X11. In that case use Option A.

> Note: the libei 1.6 client API is event-driven; this backend binds the exact
> `ei_device_*` send functions declared by the installed header and reaches the
> portal over session D-Bus. Because it depends on the portal being installed
> and on an interactive permission grant, it was not able to be exercised live
> in a headless/sandboxed environment — run the `--live` test in a real KDE
> session to confirm pointer movement and clicking.

---

## Option C — pynput backend (Jetson / X11)

The original behaviour, preserved unchanged.

```bash
pip install pynput       # already installed on the Jetson
```

Requires an X11 session. Under Wayland it is not used (auto-selection skips it
to avoid silently doing nothing).

---

## Running the application

```bash
cd vision/src
python main.py
```

The mouse backend is selected at startup and released cleanly on exit
(`main.py` calls `mouse.close()` in its `finally` block, which never leaves a
button held). To force a backend regardless of detection:

```bash
HANDMOUSE_MOUSE_BACKEND=uinput python main.py
```

## Portal and scroll semantics

The RemoteDesktop setup waits for asynchronous `Request.Response` signals,
retains the actual session handle, and closes requests on failure/timeout and
the session on shutdown. `ConnectToEIS` retrieves a descriptor from Gio's
UnixFDList; libei owns it after setup. Revoked/paused/removed devices do not
retain logical button holds. Capability-specific devices are supported.

Scroll uses wheel steps, positive Y down and positive X right, consistently
across all three backends. libei uses 120 discrete units per step; uinput
advertises both vertical and horizontal wheel axes.

Hardware note: the Jetson kernel documented in `AGENT.md` has uinput compiled
out. Group membership or installing evdev cannot create a missing kernel
feature; use pynput on X11 there unless the kernel is explicitly changed.
