from .._geometry import finger_states

NAME = "index_only"


def matches(context):
    """
    INDEX ONLY

        index  = open
        middle = closed
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
        not fingers["middle"]
        and
        not fingers["ring"]
        and
        not fingers["pinky"]
    )