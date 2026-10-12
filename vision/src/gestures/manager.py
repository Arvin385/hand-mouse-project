import importlib
import pkgutil


class GestureManager:
    """
    Discovers and manages all gesture modules inside:

        gestures/src/

    Each gesture file must expose:

        class Gesture

    A Gesture should implement:

        update(states)
        run()
        reset()

    update(states):
        returns True when the gesture should run
        during the current frame.

    run():
        performs the gesture's actual consequence.

    reset():
        clears internal gesture state.
    """

    def __init__(self):
        self._gestures = []

        self._load_gestures()

    # ========================================================
    # DISCOVERY
    # ========================================================

    def _load_gestures(self):
        """
        Automatically load all gestures from gestures/src/.
        """

        self._gestures.clear()

        package = importlib.import_module(
            "gestures.src"
        )

        for module_info in pkgutil.iter_modules(
            package.__path__
        ):
            module_name = module_info.name

            if module_name.startswith("_"):
                continue

            module = importlib.import_module(
                f"gestures.src.{module_name}"
            )

            gesture_class = getattr(
                module,
                "Gesture",
                None
            )

            if gesture_class is None:
                print(
                    f"Skipping gesture '{module_name}': "
                    f"missing Gesture class."
                )

                continue

            gesture = gesture_class()

            self._gestures.append(
                gesture
            )

        # Lower priority number runs first.
        self._gestures.sort(
            key=lambda gesture:
            getattr(
                gesture,
                "priority",
                1
            )
        )

        print(
            "Gestures loaded:",
            ", ".join(
                gesture.name
                for gesture in self._gestures
            )
        )

    # ========================================================
    # UPDATE
    # ========================================================

    def update(
        self,
        states
    ):
        """
        Check every gesture.

        Multiple gestures may be recognized during the same
        frame.

        Returns:

            [
                gesture,
                gesture,
                ...
            ]

        already sorted by priority.
        """

        ready = []

        for gesture in self._gestures:

            try:

                should_run = gesture.update(
                    states
                )

            except Exception as exc:

                print(
                    f"Gesture '{gesture.name}' "
                    f"failed during update: {exc}"
                )

                continue

            if should_run:
                ready.append(
                    gesture
                )

        return ready

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):
        """
        Reset all gestures.

        Called when the hand disappears.
        """

        for gesture in self._gestures:

            reset = getattr(
                gesture,
                "reset",
                None
            )

            if callable(reset):

                try:
                    reset()

                except Exception as exc:

                    print(
                        f"Gesture '{gesture.name}' "
                        f"failed during reset: {exc}"
                    )

    # ========================================================
    # DEBUG
    # ========================================================

    def all(self):
        """
        Return all loaded gestures.

        Useful for debugging.
        """

        return list(
            self._gestures
        )

    # ========================================================
    # RELOAD
    # ========================================================

    def reload(self):
        """
        Reload gesture discovery.

        Useful during development.
        """

        self.reset()

        self._load_gestures()