from .._geometry import finger_states, thumb_index_pinch

NAME = "index_pinch"


def matches(context):
    """
    INDEX PINCH

        middle = open
        ring   = open
        pinky  = open

        thumb tip + index tip pinched together.

    The index finger may be slightly bent or
    held straight; the pinch itself is the
    defining feature.
    """

    fingers = finger_states(
        context.landmarks
    )

    return (
        fingers["middle"]
        and
        fingers["ring"]
        and
        fingers["pinky"]
        and
        thumb_index_pinch(
            context.landmarks
        )
    )
