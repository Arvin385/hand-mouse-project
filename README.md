# Hand Mouse

Control your desktop mouse with hand gestures using a USB webcam and MediaPipe Hand Landmarker.

Built for Linux desktops running X11 or Wayland. Developed and tuned on an NVIDIA Jetson Orin Nano Super, but Jetson hardware is not required.

## Requirements

- Linux with an active graphical desktop session
- Python 3.11 recommended, or another version supported by MediaPipe
- A working MediaPipe GPU environment; there is currently no automatic CPU fallback
- A V4L2 webcam compatible with the configured capture and exposure settings
- `make`, `flock`, `setsid`, `nohup`, and `v4l2-ctl`

The hand-tracking model is included at `vision/src/hand_landmarker.task`.

## Setup

Install the system utilities:

```bash
# Ubuntu / Jetson
sudo apt install make util-linux coreutils v4l-utils

# Arch / Manjaro
sudo pacman -S make util-linux coreutils v4l-utils
```

Create a Python environment and install the dependencies from the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For Wayland, follow [Wayland setup](vision/WAYLAND-SETUP.md) for the additional libraries and permissions required by the input backends.

## Start and stop

Run these commands from the repository root, inside your graphical desktop session:

```bash
make start
make stop
```

`make start` launches the application in the background, detached from the terminal. Closing the terminal does not stop it. Repeated starts do not launch another instance while the recorded process is running.

`make stop` requests graceful shutdown and waits up to 15 seconds. Normal shutdown releases held mouse buttons and closes the camera and hand tracker. If shutdown times out, the process is not forcibly killed; inspect the log before retrying.

The application opens a debug window and controls your real mouse. Start with a safe desktop area. You can also stop it by pressing **Q** or **Esc** in the debug window.

### Logs

Output is appended to:

```text
.run/handmouse.log
```

To follow the log:

```bash
tail -f .run/handmouse.log
```

The launcher checks that the process is still alive after one second; this does not guarantee that hardware initialization has finished. Check the log for startup errors.

This is a detached process, not a system service: it does not automatically restart after failure or reboot, and operation after desktop logout is not guaranteed.

### Python interpreter

The Makefile uses `.venv/bin/python` when available, otherwise `python3`. You do not need to activate the virtual environment.

To use another interpreter:

```bash
make start PYTHON=/path/to/python
```

## Automatic backend selection

`make start` sets the mouse backend to `auto`. The application chooses based on the desktop session, not the machine model or Linux distribution:

| Desktop session | Preferred backend | Fallbacks |
| --- | --- | --- |
| X11 | `pynput` | `libei`, then `uinput` |
| Wayland | `libei` | `uinput` |

Backend availability depends on compositor support, installed libraries, kernel support, and permissions. There is no separate Jetson backend. The project Jetson's kernel has uinput compiled out, so its X11 desktop uses `pynput`.

Automatic mouse-backend selection does not guarantee compatibility with every machine. MediaPipe GPU support and webcam settings must also work on the host.


## Gestures

| Action | Gesture |
| --- | --- |
| Move cursor | Move your hand while it is not a fist. |
| Pause cursor | Make a fist. |
| Press and hold left button | Start with an unpinched open palm, then pinch thumb and index fingertips together while keeping the other fingers open. |
| Release left button | Return to an unpinched open palm. |
| Drag | Keep the pinch held while moving, then open your palm to release. |
| Double-click | Open palm → index and middle fingers extended, other fingers closed → open palm. |

A normal click is a press followed by a release. Double-click is disabled while the left button is held. Tracking loss releases held buttons for safety.

Scrolling is not implemented.

## Configuration

| Setting | File |
| --- | --- |
| Camera device and exposure | `vision/src/camera/config.py` |
| Capture resolution, frame rate, and MediaPipe GPU initialization | `vision/src/init.py` |
| Cursor gain, deadzone, and smoothing | `vision/src/gestures/src/move_cursor.py` |
| Hand-pose geometry | `vision/src/states/_geometry.py` |

The application requests a **640×480, 30 FPS** camera feed. The debug window provides sliders for exposure mode, exposure, gain, and target brightness.

Webcam controls vary. Before adjusting exposure settings, inspect your camera:

```bash
v4l2-ctl -d /dev/video0 --list-ctrls-menus
```

On the project Jetson, native automatic exposure previously reduced capture speed to about 20 FPS. Manual exposure with bounded software adjustment achieved roughly 29–30 FPS, with GPU inference around 8 ms. These are measurements from the project hardware, not guarantees for other machines.

## Foreground debugging

To run directly and see output in the terminal:

```bash
.venv/bin/python vision/src/main.py
```

Press **Ctrl+C**, **Q**, or **Esc** to stop. Stop any background instance first.

To test a specific backend, use foreground execution:

```bash
HANDMOUSE_MOUSE_BACKEND=pynput .venv/bin/python vision/src/main.py
```

Supported backend names are `pynput`, `libei`, and `uinput`. `make start` always uses automatic selection, overriding this environment variable.

## Tests

Run the automated tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Inspect backend selection without moving or clicking the mouse:

```bash
.venv/bin/python vision/src/test_mouse_backend.py
```

For a live backend check, run:

```bash
.venv/bin/python vision/src/test_mouse_backend.py --live --backend libei
```

**Warning:** this may request desktop permission and will move the cursor, click,
and scroll. Use a safe desktop area.

## Project layout

```text
Makefile                    # Detached start and graceful stop
requirements.txt            # Python dependencies
tests/                      # Automated tests
vision/src/
├── main.py                 # Application entry point and cleanup
├── init.py                 # Camera and MediaPipe initialization
├── engine.py               # Orchestration loop
├── utils.py                # Debug UI, statistics, and runtime helpers
├── camera/                 # Camera settings and exposure control
├── states/                 # Hand-pose recognition
│   └── src/                # Dynamically discovered poses
├── gestures/               # Gesture recognition and action execution
│   └── src/                # Dynamically discovered gestures
└── mouse/                  # Input backends and automatic selection
```

The processing flow is **camera → landmarks → states → gestures → actions**. Gestures own their actions, including cursor movement. Adding a pose or gesture normally does not require modifying the engine.
