from .._geometry import finger_states

NAME = "fist"


def matches(context):
    """
    FIST

        index  = closed
        middle = closed
        ring   = closed
        pinky  = closed

    Thumb is ignored.
    """

    fingers = finger_states(
        context.landmarks
    )

    return (
        not fingers["index"]
        and
        not fingers["middle"]
        and
        not fingers["ring"]
        and
        not fingers["pinky"]
    )