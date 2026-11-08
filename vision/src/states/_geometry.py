import math


# ============================================================
# FINGER LANDMARKS
# ============================================================

FINGERS = {
    "index": {
        "mcp": 5,
        "pip": 6,
        "dip": 7,
        "tip": 8,
    },

    "middle": {
        "mcp": 9,
        "pip": 10,
        "dip": 11,
        "tip": 12,
    },

    "ring": {
        "mcp": 13,
        "pip": 14,
        "dip": 15,
        "tip": 16,
    },

    "pinky": {
        "mcp": 17,
        "pip": 18,
        "dip": 19,
        "tip": 20,
    },
}


# ============================================================
# TUNING
# ============================================================

# Straight finger ~= 180 degrees.

PIP_OPEN_ANGLE = 155
DIP_OPEN_ANGLE = 150

# Thumb + index pinch.
#
# The thumb tip and index tip are considered
# pinched when their distance is below this
# fraction of the hand width
# (index MCP -> pinky MCP).

PINCH_MAX_RATIO = 0.5


# ============================================================
# GEOMETRY
# ============================================================

def angle_between(
    point_a,
    point_b,
    point_c
):
    """
    Calculate angle ABC.

        A
         \
          B ----- C

    A straight joint approaches 180 degrees.
    """

    ba_x = point_a.x - point_b.x
    ba_y = point_a.y - point_b.y

    bc_x = point_c.x - point_b.x
    bc_y = point_c.y - point_b.y

    magnitude_ba = math.sqrt(
        ba_x * ba_x
        +
        ba_y * ba_y
    )

    magnitude_bc = math.sqrt(
        bc_x * bc_x
        +
        bc_y * bc_y
    )

    if (
        magnitude_ba < 1e-6
        or
        magnitude_bc < 1e-6
    ):
        return 0.0

    cosine = (
        ba_x * bc_x
        +
        ba_y * bc_y
    ) / (
        magnitude_ba
        *
        magnitude_bc
    )

    cosine = max(
        -1.0,
        min(
            1.0,
            cosine
        )
    )

    return math.degrees(
        math.acos(
            cosine
        )
    )


def distance(
    point_a,
    point_b
):
    """
    Euclidean distance between two landmarks.
    """

    dx = point_b.x - point_a.x

    dy = point_b.y - point_a.y

    return math.sqrt(
        dx * dx
        +
        dy * dy
    )


# ============================================================
# FINGER STATE
# ============================================================

def finger_is_open(
    landmarks,
    finger_name
):
    """
    Determine whether a finger is extended.

    Thumb is intentionally not handled here yet.
    """

    finger = FINGERS[
        finger_name
    ]

    mcp = landmarks[
        finger["mcp"]
    ]

    pip = landmarks[
        finger["pip"]
    ]

    dip = landmarks[
        finger["dip"]
    ]

    tip = landmarks[
        finger["tip"]
    ]

    pip_angle = angle_between(
        mcp,
        pip,
        dip
    )

    dip_angle = angle_between(
        pip,
        dip,
        tip
    )

    return (
        pip_angle >= PIP_OPEN_ANGLE
        and
        dip_angle >= DIP_OPEN_ANGLE
    )


def finger_states(
    landmarks
):
    """
    Return the open/closed status of all four primary fingers.

    Example:

        {
            "index": True,
            "middle": False,
            "ring": False,
            "pinky": False
        }
    """

    return {
        finger_name:
            finger_is_open(
                landmarks,
                finger_name
            )

        for finger_name
        in FINGERS
    }


# ============================================================
# THUMB INDEX PINCH
# ============================================================

def pinch_ratio(
    landmarks
):
    """
    Distance between the thumb tip (4) and the
    index tip (8), normalized by the hand width.

    0 means the tips are touching.

    The hand width is measured between the
    index MCP (5) and the pinky MCP (17).
    """

    hand_width = distance(
        landmarks[5],
        landmarks[17]
    )

    if hand_width < 1e-6:
        # A collapsed reference width cannot establish a pinch.
        return math.inf

    return distance(
        landmarks[4],
        landmarks[8]
    ) / hand_width


def thumb_index_pinch(
    landmarks
):
    """
    True when the thumb tip and the index tip
    are close together relative to the hand size.
    """

    return pinch_ratio(
        landmarks
    ) <= PINCH_MAX_RATIO