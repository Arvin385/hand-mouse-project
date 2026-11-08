CAMERA_DEVICE = "/dev/video0"

CAMERA_AUTO_EXPOSURE = 1
CAMERA_EXPOSURE = 200
CAMERA_GAIN = 32

CAMERA_EXPOSURE_MIN = 20
CAMERA_EXPOSURE_MAX = 200

CAMERA_GAIN_MIN = 0
CAMERA_GAIN_MAX = 63

# Device-specific hard limits reported for the current laptop webcam.
# Not universal Jetson/USB camera limits: verify with v4l2-ctl --list-ctrls
# before configuring a different device. Preserve these for this laptop.
# Software auto uses the intersection with the tuning ranges above, so its
# effective exposure minimum here is 50, not the requested 20.
CAMERA_EXPOSURE_HARD_MIN = 50
CAMERA_EXPOSURE_HARD_MAX = 10000

CAMERA_GAIN_HARD_MIN = 0
CAMERA_GAIN_HARD_MAX = 128