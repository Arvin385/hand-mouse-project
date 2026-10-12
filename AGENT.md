# Hand Mouse Project — Agent Handoff

> **Purpose:** Read this file before modifying this repository. It records architecture decisions, hardware-specific measurements, debugging discoveries, and implementation constraints that took substantial trial-and-error to establish.
>
> **Primary goal:** A low-latency, extensible hand-controlled mouse using an NVIDIA Jetson Orin Nano Super + USB webcam + MediaPipe Hand Landmarker. The design must make it easy to add new hand states and gestures without changing the engine.

---

## 1. First rule for any coding agent

Before changing code, inspect the repository as it actually exists:

```bash
pwd
tree -L 5
grep -R "class Gesture\|class StateManager\|def matches\|def run\|def update" -n .
```

Do **not** assume this document is a byte-for-byte description of the current files. It describes the intended architecture and the known-good hardware/runtime behavior. Preserve those architectural boundaries unless the user explicitly changes them.

The user strongly prefers a simple, modular design over clever abstractions. `engine.py` should read almost like pseudocode.

---

# 2. Target hardware/runtime

## Target device

Confirmed target board:

```text
NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super
```

Observed kernel:

```text
5.15.199-tegra
```

The system was observed in the Jetson Linux 36.5.2 family. NVIDIA's JetPack archive maps:

```text
JetPack 6.2.3 -> L4T / Jetson Linux 36.5.2
```

Do not blindly infer the installed JetPack version from this document on future machines; verify locally.

Useful checks:

```bash
uname -a
cat /etc/nv_tegra_release
sudo nvpmodel -q
```

The repository may also be edited from a non-Jetson development machine. Before executing Jetson-specific commands, verify which machine is currently running the shell.

---

# 3. Jetson power-mode discoveries

On this specific Jetson, `/etc/nvpmodel.conf` exposed:

```text
ID 0 = 15W
ID 1 = 25W
ID 2 = MAXN_SUPER
```

The board initially ran in 15W mode.

NVIDIA documentation confirms that Orin Nano Super configurations support high-power `MAXN_SUPER` modes. Exact mode IDs/configurations can vary, so always inspect the device's own `nvpmodel.conf`.

Important debugging notes:

- `sudo jetson_clocks --restore` can fail if `/root/.jetsonclocks_conf.txt` does not exist. This simply means no prior `jetson_clocks --store` configuration exists; it is not by itself evidence of a broken system.
- `sudo jetson_clocks --fan` forces fan behavior. Do **not** use this for normal operation.
- Prefer normal fan control (`nvfancontrol` service) unless explicitly benchmarking.
- If fan control was forced during testing, restoring/restarting NVIDIA fan control is preferable to permanently forcing the fan.

Useful official reference:
- NVIDIA Orin power/performance guide:
  https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html
- NVIDIA JetPack archive:
  https://developer.nvidia.com/embedded/jetpack-archive

---

# 4. MediaPipe: critical facts learned experimentally

## Package/API

The installed MediaPipe environment used Python 3.10 and MediaPipe `1.0.1`.

Do **not** assume the old:

```python
mp.solutions
```

API exists. It did not in this environment.

The working API is the Tasks API:

```python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
```

Model file:

```text
hand_landmarker.task
```

Working configuration:

```python
options = vision.HandLandmarkerOptions(
    base_options=BaseOptions(
        model_asset_path=MODEL_PATH,
        delegate=BaseOptions.Delegate.GPU,
    ),
    running_mode=vision.RunningMode.VIDEO,
    num_hands=1,
    min_hand_detection_confidence=0.5,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)
```

## GPU result

A major discovery: **the MediaPipe GPU delegate works on this Jetson setup**.

Measured results:

```text
CPU MediaPipe inference: roughly 34-45 ms
CPU overall loop:        roughly 18-20 FPS

GPU MediaPipe inference: roughly 8 ms
GPU overall loop:        roughly 29 FPS
```

Therefore:

- Do not migrate to TensorRT merely because "Jetson usually needs TensorRT."
- MediaPipe GPU is already fast enough for the current 30 FPS camera.
- The webcam, not inference, is currently the main frame-rate ceiling.

Google's current MediaPipe Tasks docs expose `BaseOptions.Delegate.GPU`; official docs say GPU is supported on Ubuntu platforms:
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/BaseOptions
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarkerOptions

## VIDEO timestamp requirement

`RunningMode.VIDEO` uses:

```python
landmarker.detect_for_video(image, timestamp_ms)
```

Timestamps must be monotonically increasing.

The initialization code should protect against duplicate millisecond timestamps, e.g. conceptually:

```python
timestamp_ms = int((time.monotonic() - origin) * 1000)

if timestamp_ms <= last_timestamp_ms:
    timestamp_ms = last_timestamp_ms + 1
```

This is important. Do not replace it with an unsafe timestamp source.

---

# 5. USB webcam: the most important debugging discoveries

The USB webcam advertises MJPEG and YUYV modes.

Observed capabilities included:

```text
MJPG:
    up to 30 FPS at common resolutions including
    1920x1080, 1280x720, 640x480

YUYV:
    30 FPS at 640x480
    lower FPS at higher resolutions
```

For this project, the known-good mode is:

```text
/dev/video0
V4L2
MJPG
640x480
30 FPS
```

OpenCV configuration:

```python
cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

cap.set(
    cv2.CAP_PROP_FOURCC,
    cv2.VideoWriter_fourcc(*"MJPG"),
)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
```

## Critical discovery #1: automatic exposure reduced actual FPS

The camera originally delivered only about:

```text
~19.9 FPS
```

despite advertising 30 FPS.

The cause was automatic exposure choosing a long exposure time.

Relevant V4L2 controls observed on this webcam:

```text
auto_exposure
exposure_time_absolute
gain
```

Observed exposure control range:

```text
exposure_time_absolute:
    min = 1
    max = 5000
    default/auto-observed around 313
```

On this webcam the values behaved as approximately 100 microseconds per unit:

```text
200 ~= 20 ms
313 ~= 31.3 ms
```

This unit interpretation is based on this webcam's observed V4L2 behavior; verify on replacement hardware.

Known-good manual controls:

```text
auto_exposure=1
exposure_time_absolute=200
gain=32
```

Here `auto_exposure=1` is the webcam's **manual exposure mode**. Do not assume the integer meanings are universal; `v4l2-ctl --list-ctrls-menus` is authoritative for the attached webcam.

## Critical discovery #2: control ordering matters

This was unusually important:

> **Open and configure the camera with OpenCV first, THEN apply V4L2 exposure/gain controls.**

Applying controls before OpenCV opened/configured `/dev/video0` resulted in poor actual capture rates around 14-20 FPS.

The working order was:

```python
cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

subprocess.run([
    "v4l2-ctl",
    "-d", "/dev/video0",
    "--set-ctrl=auto_exposure=1",
    "--set-ctrl=exposure_time_absolute=200",
    "--set-ctrl=gain=32",
], check=True)
```

Measured result after fixing the order:

```text
Width:           640
Height:          480
Requested FPS:   30
FOURCC:          MJPG
Frames:          298
Elapsed:         10.00 s
OpenCV grab FPS: 29.79
```

This is a key project invariant. If camera FPS regresses, check this before redesigning anything.

## Current performance target

The webcam is effectively a 30 FPS source for this setup.

Do not chase "40+ camera FPS" unless the camera hardware is replaced or a mode supporting it is discovered.

Cursor motion may later be interpolated/smoothed at a higher display/update rate, but that does not create new camera observations.

---

# 6. Adaptive exposure without sacrificing FPS

The camera was later too bright under different daytime lighting.

Do **not** simply re-enable the webcam's native automatic exposure: it previously reduced capture FPS.

Current design:

1. Keep webcam in manual exposure mode.
2. Start from the known-good settings:
   ```text
   exposure = 200
   gain = 32
   ```
3. Run a small software exposure controller from the normal engine loop.
4. No background thread for v1.
5. Check brightness only every ~10 frames.
6. Only issue `v4l2-ctl` writes when a change is actually needed.
7. Keep exposure bounded so it cannot consume the 33.3 ms frame interval.

Initial tuning values discussed:

```text
EXPOSURE_MIN = 20
EXPOSURE_MAX = 200

GAIN_MIN = 0
GAIN_MAX = 63

TARGET_BRIGHTNESS = 115
BRIGHTNESS_TOLERANCE = 15

EXPOSURE_STEP = 10
GAIN_STEP = 2

CHECK_EVERY_FRAMES = 10
```

Brightness measurement can downsample to about `160x120`, convert to grayscale, and use a percentile such as the 60th percentile rather than a plain mean to reduce sensitivity to one bright window/lamp.

Engine order:

```text
read camera
    ↓
software exposure update
    ↓
MediaPipe hand detection
    ↓
states
    ↓
gestures
```

No thread unless measurements later prove that V4L2 control writes cause unacceptable frame spikes.

## Camera package naming

Current/recommended package concept:

```text
camera/
├── __init__.py
├── exposure.py
└── config.py        # recommended shared source of camera constants
```

There is **no `camera/init.py`** unless someone explicitly creates one.

The repository also has a root-level:

```text
init.py
```

These are different things.

Do not write:

```python
from camera.init import ...
```

unless `camera/init.py` genuinely exists.

Recommended shared settings live in `camera/config.py` so root `init.py` and `camera/exposure.py` do not duplicate values or import each other.

Example:

```python
# camera/config.py
CAMERA_DEVICE = "/dev/video0"
CAMERA_AUTO_EXPOSURE = 1
CAMERA_EXPOSURE = 200
CAMERA_GAIN = 32
```

Prefer the exported instance name:

```python
exposure_controller
```

rather than exporting an instance named `exposure`, because `camera.exposure` is also the module name.

---

# 7. Linux mouse injection: do not repeat the uinput dead end

The initial preferred design was Linux `/dev/uinput` via `evdev`.

It does **not** work on the current Jetson kernel as shipped.

Observed facts:

```text
/dev/uinput          does not exist
/dev/input/uinput    does not exist
/proc/misc           has no uinput entry
```

Kernel configuration showed:

```text
# CONFIG_INPUT_UINPUT is not set
```

And:

```bash
sudo modprobe uinput
```

failed with:

```text
FATAL: Module uinput not found in directory /lib/modules/5.15.199-tegra
```

This means uinput is not merely "not loaded"; it is compiled out of the current kernel configuration.

Do not waste time installing `python-evdev` and expecting `/dev/uinput` to appear.

Linux kernel documentation confirms that uinput normally provides `/dev/uinput` or `/dev/input/uinput` for userspace-created virtual devices:
- https://docs.kernel.org/input/uinput.html

Long-term options:

- build/install a compatible `uinput.ko` or rebuild the Jetson kernel with `CONFIG_INPUT_UINPUT`;
- use another input-injection backend appropriate to the display session;
- later use a network KVM/input-sharing architecture.

Current temporary mouse backend:

```text
pynput
```

This is intended for the current desktop environment. Before diagnosing `pynput`, check:

```bash
echo $XDG_SESSION_TYPE
```

X11 vs Wayland matters.

---

# 8. Architecture: preserve these boundaries

The user explicitly rejected a large "smart engine."

## Top-level responsibility

```text
main.py
    starts the application

init.py
    owns hardware/runtime initialization

engine.py
    owns the interactive orchestration loop only

utils.py
    owns engine support/debug/statistics/shutdown helpers

states/
    owns instantaneous hand-pose recognition

gestures/
    owns temporal/continuous behavior AND action execution

camera/
    owns runtime camera helpers such as software exposure control
```

## Desired flow

```text
main.py
   ↓
root init.py
   ├── validate model
   ├── initialize MediaPipe GPU
   ├── open/configure webcam
   ├── apply camera controls AFTER OpenCV configuration
   ├── warm up
   └── self-test
   ↓
returns initialized app
   ↓
engine.py
   ↓
interactive loop
```

Inside the engine:

```text
read frame
    ↓
update exposure
    ↓
detect hand
    ↓
get landmarks
    ↓
update states
    ↓
check all gestures
    ↓
run every ready gesture
    ↓
stats/debug
    ↓
repeat
```

The engine should be readable like:

```python
frame = self._read_camera()

self._update_exposure(frame)

detection = self._detect_hand(frame)

landmarks = self._get_landmarks(detection)

if landmarks is None:
    self._handle_no_hand(frame)
    continue

self._update_states(frame, detection, landmarks)

ready_gestures = self._check_gestures()

self._run_gestures(ready_gestures)
```

The step functions may live at the bottom of `engine.py`; this is intentional because it keeps the loop readable.

---

# 9. Important engine rules

`engine.py` must **not**:

- define states;
- calculate finger geometry;
- define gestures;
- know gesture state machines;
- manually dispatch `"move_cursor"`, `"left_down"`, `"double_click"`, etc.;
- contain a giant action `if/elif` chain;
- decide gesture priority;
- decide which gestures are allowed simultaneously.

The user explicitly requested dynamic behavior.

The expected model is:

```python
ready_gestures = gestures.update(states)

for gesture in ready_gestures:
    gesture.run()
```

The gesture owns its consequence.

For example:

- `MoveCursor.run()` moves the pointer;
- `LeftDown.run()` presses and holds the button;
- `LeftUp.run()` releases it;
- `DoubleClick.run()` double-clicks.

The engine does not need to know what any of these actions mean.

Adding a new correctly formed file under `gestures/src/` should normally require **no engine modification**.

---

# 10. `utils.py` boundary

The user asked to move engine housekeeping out of `engine.py`.

`utils.py` / `EngineUtils` should own things such as:

```text
stop
shutdown
show_debug
update_stats
record_inference
```

The exact implementation may evolve, but do not bloat the core loop with bookkeeping.

Debug state checks are allowed because they do not drive application behavior.

---

# 11. State package design

Intended structure:

```text
states/
├── __init__.py
├── manager.py
├── _geometry.py
└── src/
    ├── __init__.py
    ├── fist.py
    ├── open_palm.py
    ├── index_only.py
    └── two_fingers.py
```

Important Python packaging detail:

```text
__init__.py
```

must be spelled exactly that way.

A previous typo existed in another package as:

```text
__init.py
```

which is not equivalent.

## State package public API

`states/__init__.py` should expose a ready-to-use object, conceptually:

```python
from .manager import StateManager

states = StateManager()
```

Engine imports:

```python
from states import states
```

## State discovery

`StateManager` must scan:

```python
states.src
```

not the top-level `states` package.

Otherwise it sees the `src` directory itself as if it were a state and prints errors such as:

```text
Skipping state 'src': missing NAME.
States loaded:
```

Correct concept:

```python
package = importlib.import_module("states.src")
```

and state modules are imported as:

```python
states.src.<module_name>
```

## State module interface

Each actual state file should expose:

```python
NAME = "state_name"

def matches(context):
    return True_or_False
```

The manager may expose:

```python
states.update(...)
states.reset()
states.active()
states.is_active("fist")
states.context
```

## Shared geometry import

`_geometry.py` lives at:

```text
states/_geometry.py
```

Actual state files live one package deeper:

```text
states/src/fist.py
```

Therefore imports from a state file must be:

```python
from .._geometry import finger_states
```

NOT:

```python
from ._geometry import finger_states
```

The latter incorrectly searches for:

```text
states/src/_geometry.py
```

and caused:

```text
ModuleNotFoundError: No module named 'states.src._geometry'
```

---

# 12. State semantics for v1

The four-finger states below intentionally ignore the thumb. INDEX_PINCH is the first state that uses the thumb.

Current states:

```text
FIST
    index closed
    middle closed
    ring closed
    pinky closed

OPEN_PALM
    index open
    middle open
    ring open
    pinky open

INDEX_ONLY
    index open
    middle closed
    ring closed
    pinky closed

TWO_FINGERS
    index open
    middle open
    ring closed
    pinky closed

INDEX_PINCH
    middle open
    ring open
    pinky open
    thumb tip (4) + index tip (8) pinched together
```

Current geometry approach uses joint angles, not only screen-space tip positions.

Initial thresholds discussed:

```text
PIP_OPEN_ANGLE = 155 degrees
DIP_OPEN_ANGLE = 150 degrees

PINCH_MAX_RATIO = 0.5
    thumb-tip to index-tip distance as a fraction
    of hand width (index MCP 5 -> pinky MCP 17)
```

These are tuning values, not immutable truths.

MediaPipe landmark indices used for the four non-thumb fingers:

```text
index:  MCP 5,  PIP 6,  DIP 7,  TIP 8
middle: MCP 9,  PIP 10, DIP 11, TIP 12
ring:   MCP 13, PIP 14, DIP 15, TIP 16
pinky:  MCP 17, PIP 18, DIP 19, TIP 20
```

Thumb landmarks used by INDEX_PINCH:

```text
wrist 0,  thumb TIP 4
pinch reference: index TIP 8, hand width 5 -> 17
```

---

# 13. Gesture package design

Intended structure:

```text
gestures/
├── __init__.py
├── manager.py
├── _mouse.py
└── src/
    ├── __init__.py
    ├── move_cursor.py
    ├── left_down.py
    ├── left_up.py
    └── double_click.py
```

`gestures/__init__.py` should expose:

```python
from .manager import GestureManager

gestures = GestureManager()
```

Engine imports only:

```python
from gestures import gestures
```

## Gesture discovery

`GestureManager` scans:

```python
gestures.src
```

and dynamically instantiates each module's `Gesture` class.

Expected interface:

```python
class Gesture:
    name = "..."
    priority = ...

    def update(self, states):
        # return True when this gesture should run this frame
        ...

    def run(self):
        # perform its consequence
        ...

    def reset(self):
        ...
```

All gesture recognizers are checked every frame.

More than one gesture may be ready on the same frame.

Lower priority number runs first.

For now:

```text
move_cursor priority = 0
all other v1 gestures priority = 1
```

Do not add exclusivity/blocking unless behavior demonstrates a need for it.

---

# 14. Fundamental gesture philosophy

The user intentionally decided:

> **Everything the hand does is a gesture. No special controller exception.**

This includes cursor movement.

There is no conceptual `controllers/cursor.py` in the chosen design.

Cursor movement is simply a **continuous gesture**.

All gestures can coexist unless their own recognition/action logic makes that impossible.

---

# 15. V1 gestures and exact intended behavior

No scrolling in v1.

## `move_cursor`

Priority:

```text
0
```

Recognition rule:

```text
a hand is detected
AND
the hand is NOT FIST
```

Important: cursor movement is allowed even if none of the other named poses match. `FIST` is the explicit "do not move cursor" pose.

Therefore during `INDEX_ONLY`, `TWO_FINGERS`, or other non-fist forms, the cursor may continue to follow the hand.

This is intentional so dragging works.

Initial palm center used landmarks:

```text
0, 5, 9, 13, 17
```

Initial tuning discussed:

```text
GAIN_X = 3200
GAIN_Y = 3200
DEADZONE = 0.0015
MAX_STEP = 100
SMOOTHING = 0.55
```

These are starting values and should be tuned experimentally.

## `left_down`

This replaces the idea of a monolithic "single click."

Intended sequence:

```text
OPEN_PALM
    ↓
INDEX_ONLY
    ↓
LEFT MOUSE DOWN
```

The OS mouse button remains held.

A short stable-frame requirement (~3 frames at 30 FPS) was proposed to reduce accidental activation.

## `left_up`

Intended behavior:

```text
LEFT BUTTON CURRENTLY HELD
    +
OPEN_PALM
    ↓
LEFT MOUSE UP
```

This decomposition is deliberate because it produces drag naturally:

```text
left_down
    ↓
move_cursor
move_cursor
move_cursor
    ↓
left_up
```

There is no separate `drag.py` needed for v1.

## `double_click`

Intended sequence:

```text
OPEN_PALM
    ↓
TWO_FINGERS
    ↓
OPEN_PALM
    ↓
DOUBLE CLICK
```

It should not fire while the left mouse button is already held.

---

# 16. Shared mouse behavior

`gestures/_mouse.py` owns the shared `pynput` mouse controller.

This is intentional:

- gestures execute their own actions;
- engine does not dispatch action types;
- `left_down` and `left_up` must share button state.

Mouse button operations should be idempotent:

```text
left_down when already down -> no-op
left_up when already up     -> no-op
```

Safety rule:

> If hand tracking disappears or the application shuts down, do not leave the OS left mouse button stuck down.

A gesture reset or global gesture-manager reset should ensure a held button can be released safely.

---

# 17. `main.py` should stay tiny

Conceptual flow:

```python
from init import initialize
from engine import Engine

def main():
    app = initialize()

    try:
        Engine(app=app, debug=True).run()
    finally:
        app.shutdown()

if __name__ == "__main__":
    main()
```

Root `init.py` owns camera and MediaPipe resources.

`engine.py` should not close resources that belong to `init.py`.

---

# 18. Root `init.py`: known-good responsibilities

The root-level `init.py` should be setup/hardware-only.

It should:

```text
verify hand_landmarker.task
initialize MediaPipe GPU
open webcam with V4L2
set MJPG 640x480 30
apply V4L2 exposure/gain AFTER OpenCV configuration
warm up camera
run a small self-test
expose read_frame()
expose detect_hands(frame)
provide safe monotonically increasing timestamps
shutdown camera + MediaPipe
```

It should not contain:

```text
gesture recognition
state recognition
cursor logic
click state machines
```

Known camera constants:

```python
CAMERA_AUTO_EXPOSURE = 1
CAMERA_EXPOSURE = 200
CAMERA_GAIN = 32
```

If these settings are also needed by `camera/exposure.py`, prefer moving the shared constants to `camera/config.py` rather than duplicating them or importing the root `init.py` from the camera package.

---

# 19. Current/recent package-layout pitfalls

These caused real integration errors and should be checked immediately when imports fail.

## Wrong `__init__` filename

Wrong:

```text
gestures/src/__init.py
```

Correct:

```text
gestures/src/__init__.py
```

## Wrong state scanner target

Wrong:

```python
importlib.import_module("states")
```

for discovery.

Correct:

```python
importlib.import_module("states.src")
```

## Wrong relative geometry import

From `states/src/fist.py`:

Wrong:

```python
from ._geometry import finger_states
```

Correct:

```python
from .._geometry import finger_states
```

## `camera.init` confusion

Root file:

```text
src/init.py
```

Package initializer:

```text
src/camera/__init__.py
```

These do **not** imply a module named:

```text
camera.init
```

Unless this file actually exists:

```text
camera/init.py
```

`from camera.init import ...` will fail.

---

# 20. Debugging order: use this before redesigning anything

If the program fails, debug in this order.

## Import/package failures

```bash
tree -L 5
find . -name "__init*" -print
python -c "import states; print(states.__file__); print(dir(states))"
python -c "import gestures; print(gestures.__file__); print(dir(gestures))"
python -c "import camera; print(camera.__file__); print(dir(camera))"
```

If `module.__file__` is `None` unexpectedly, check package `__init__.py` files and naming conflicts.

## Camera FPS regression

Check:

1. V4L2 backend is used.
2. MJPG is actually selected.
3. Resolution is 640x480.
4. FPS request is 30.
5. Camera controls are applied **after** OpenCV opens/configures the device.
6. Native camera automatic exposure has not been re-enabled.
7. Exposure is not being allowed near/beyond the frame interval.

Useful commands:

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
v4l2-ctl -d /dev/video0 --list-ctrls-menus
v4l2-ctl -d /dev/video0 --get-ctrl=auto_exposure
v4l2-ctl -d /dev/video0 --get-ctrl=exposure_time_absolute
v4l2-ctl -d /dev/video0 --get-ctrl=gain
```

## Hand inference regression

Confirm GPU delegate is still used and measure inference time separately from total loop FPS.

Expected order of magnitude from this machine:

```text
~8 ms MediaPipe GPU inference
~29 FPS total loop
```

If inference remains ~8 ms but total loop falls to ~20 FPS, suspect camera/exposure first.

## Mouse injection failure

Do not assume uinput.

Check:

```bash
echo $XDG_SESSION_TYPE
ls -l /dev/uinput /dev/input/uinput
grep CONFIG_INPUT_UINPUT /boot/config-$(uname -r) 2>/dev/null
```

Current Jetson kernel previously reported uinput compiled out.

---

# 21. Development priorities / next likely work

When asked what to work on next, prefer measurement and tuning over architecture churn.

Likely sequence:

1. Get the entire current program importing and running end-to-end.
2. Verify camera remains ~29-30 FPS with the software exposure controller enabled.
3. Show/log active states and confirm:
   - fist
   - open palm
   - index only
   - two fingers
4. Tune finger-angle thresholds if states flicker.
5. Tune cursor gain/deadzone/smoothing with actual hand motion.
6. Verify click-down / drag / click-up behavior.
7. Verify double-click does not conflict with drag.
8. Add debouncing/hysteresis only where measurements show it is necessary.
9. Only then add new gestures/features.
10. Later: investigate LAN multi-device control/input sharing.

No scrolling yet unless the user explicitly asks for it.

---

# 22. Longer-term multi-device goal

The user eventually wants to control multiple computers over LAN without physically unplugging/replugging mouse/keyboard devices.

This is not part of v1 gesture recognition.

A software KVM/input-sharing layer such as Deskflow was previously considered as a future direction.

Keep local hand recognition and gesture semantics independent of whichever local/LAN output backend is chosen later.

---

# 23. Design principles to preserve

When proposing changes, optimize for:

```text
low latency
easy debugging
small modules
dynamic discovery
clear ownership
few hidden side effects
measured behavior over assumptions
```

Avoid:

```text
large god classes
engine-side state recognition
engine-side action dispatch tables
premature threading
premature TensorRT migration
hardcoded gesture lists in engine.py
native webcam auto-exposure that changes FPS
assuming uinput exists
```

The most important architectural invariant is:

```text
LANDMARKS
    ↓
STATES
    ↓
GESTURES
    ↓
Gesture.run()
    ↓
ACTION
```

with the engine acting only as the orchestration loop.

---

# 24. Known measured facts vs. tuning assumptions

Treat these as **measured on the project hardware** unless re-tested:

```text
MediaPipe CPU inference: ~34-45 ms
MediaPipe GPU inference: ~8 ms
GPU loop: ~29 FPS
manual exposure fixed camera capture near 29.79 FPS
native auto exposure previously reduced capture to ~19.9 FPS
camera-control ordering affected actual FPS
uinput is compiled out of the observed Jetson kernel
```

Treat these as **initial tuning choices**, not hardware truths:

```text
state joint-angle thresholds
cursor gain
cursor smoothing
cursor deadzone
gesture stable-frame counts
gesture timeouts
software exposure target brightness
software exposure step sizes
software exposure check frequency
```

Always measure before making a large architectural change.

---

# 25. External references worth retaining

These official sources were explicitly useful during debugging:

### NVIDIA

JetPack archive; maps JetPack releases to L4T/Jetson Linux:
https://developer.nvidia.com/embedded/jetpack-archive

Jetson software documentation index:
https://docs.nvidia.com/jetson/

Orin Nano/NX power and performance documentation:
https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html

### MediaPipe

`BaseOptions` and delegate selection:
https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/BaseOptions

`HandLandmarkerOptions`:
https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarkerOptions

### Linux input

Kernel uinput documentation:
https://docs.kernel.org/input/uinput.html

---

# 26. Handoff summary for a coding model

If you only remember ten things, remember these:

1. **MediaPipe Tasks + GPU already works on the Jetson (~8 ms inference).**
2. **The camera is the ~30 FPS ceiling; don't prematurely rewrite inference in TensorRT.**
3. **Native auto exposure caused the webcam to fall to ~20 FPS.**
4. **Open/configure OpenCV first; apply V4L2 manual exposure/gain afterward. This ordering mattered.**
5. **Use software-bounded exposure adaptation instead of native auto exposure.**
6. **`uinput` is compiled out of the current Jetson kernel; `pynput` is the temporary backend.**
7. **Engine must stay thin and pseudocode-like.**
8. **States live in `states/src`; gestures live in `gestures/src`; managers dynamically discover them.**
9. **Every hand behavior is a gesture, including cursor movement. Multiple gestures may run simultaneously.**
10. **Gestures own their actions via `Gesture.run()`; engine must never hardcode action names.**

When unsure, inspect the running code and measure the hardware before changing the architecture.
