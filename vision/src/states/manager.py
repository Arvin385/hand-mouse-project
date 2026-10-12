import importlib
import pkgutil

from dataclasses import dataclass


@dataclass
class StateContext:
    """
    Information available to every state recognizer.

    State files should inspect this context and return
    True or False from matches().
    """

    landmarks: object
    frame: object
    detection: object

    timestamp: float
    frame_number: int

    width: int
    height: int


class StateManager:
    """
    Loads and manages all hand states.

    Engine usage:

        states.update(...)
        states.active()
        states.is_active("fist")

    Gesture usage:

        if states.is_active("index_only"):
            ...
    """

    def __init__(self):
        self._state_modules = {}

        self._results = {}

        self.context = None

        self._load_states()

    # ========================================================
    # STATE DISCOVERY
    # ========================================================
    def _load_states(self):
        self._state_modules.clear()

        package = importlib.import_module(
            "states.src"
        )

        for module_info in pkgutil.iter_modules(
            package.__path__
        ):
            module_name = module_info.name

            if module_name.startswith("_"):
                continue

            module = importlib.import_module(
                f"states.src.{module_name}"
            )

            state_name = getattr(
                module,
                "NAME",
                None
            )

            matches = getattr(
                module,
                "matches",
                None
            )

            if state_name is None:
                print(
                    f"Skipping state '{module_name}': "
                    f"missing NAME."
                )
                continue

            if not callable(matches):
                print(
                    f"Skipping state '{module_name}': "
                    f"missing matches(context)."
                )
                continue

            self._state_modules[state_name] = module

        print(
            "States loaded:",
            ", ".join(
                self._state_modules.keys()
            )
        )

    # ========================================================
    # FRAME UPDATE
    # ========================================================

    def update(
        self,
        landmarks,
        frame,
        detection,
        timestamp,
        frame_number
    ):
        """
        Evaluate every registered state for the current frame.
        """

        height, width = frame.shape[:2]

        self.context = StateContext(
            landmarks=landmarks,

            frame=frame,

            detection=detection,

            timestamp=timestamp,

            frame_number=frame_number,

            width=width,
            height=height
        )

        self._results.clear()

        for name, module in (
            self._state_modules.items()
        ):
            try:

                self._results[name] = bool(
                    module.matches(
                        self.context
                    )
                )

            except Exception as exc:

                print(
                    f"State '{name}' failed: {exc}"
                )

                self._results[name] = False

    # ========================================================
    # QUERY
    # ========================================================

    def is_active(
        self,
        name
    ):
        """
        Return whether a specific state is active.

        Example:

            states.is_active("fist")
        """

        return self._results.get(
            name,
            False
        )

    def active(self):
        """
        Return all currently active state names.

        Primarily useful for debugging.
        """

        return [
            name

            for name, active
            in self._results.items()

            if active
        ]

    def get(
        self,
        name
    ):
        """
        Alias for is_active().

        Allows:

            states.get("fist")
        """

        return self.is_active(
            name
        )

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):
        """
        Clear the current hand state.

        Called when no hand is visible.
        """

        self.context = None

        self._results.clear()

    # ========================================================
    # OPTIONAL RELOAD
    # ========================================================

    def reload(self):
        """
        Reload state modules.

        Useful during development if we later want
        hot-reloading.
        """

        self.reset()

        self._load_states()