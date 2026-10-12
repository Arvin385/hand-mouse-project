from .._geometry import finger_states

NAME = "two_fingers"


def matches(context):
    """
    TWO FINGERS

        index  = open
        middle = open
        ring   = closed
        pinky  = closed

    Thumb is ignored.
    """

    fingers = finger_states(
        context.landmarks
    )

    return (
        fingers["index"]
        and
        fingers["middle"]
        and
        not fingers["ring"]
        and
        not fingers["pinky"]
    )