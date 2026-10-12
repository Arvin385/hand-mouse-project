from .._geometry import finger_states

NAME = "open_palm"


def matches(context):
    """
    OPEN PALM

        index  = open
        middle = open
        ring   = open
        pinky  = open

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
        fingers["ring"]
        and
        fingers["pinky"]
    )