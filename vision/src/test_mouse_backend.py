"""Non-injecting policy diagnostic; --live explicitly enables real input."""
import argparse
import sys


def check_interface(instance):
    """Inspection only: never invoke an input-producing method."""
    for name in ("move_relative", "move_absolute", "button_down", "button_up",
                 "is_button_down", "click", "scroll", "release_all", "close"):
        if not callable(getattr(instance, name, None)):
            raise AssertionError(f"missing backend method: {name}")


def live_check(instance):
    from mouse import Button
    instance.move_relative(30, 0)
    instance.move_relative(-30, 0)
    instance.button_down(Button.LEFT)
    instance.button_down(Button.LEFT)
    instance.button_up(Button.LEFT)
    instance.button_up(Button.LEFT)
    instance.scroll(0, 1)
    instance.scroll(0, -1)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="construct backend and inject movement, click and scroll")
    parser.add_argument("--backend", default="auto", choices=("auto", "pynput", "uinput", "libei"))
    args = parser.parse_args(argv)
    from mouse.factory import backend_candidates, create_mouse_backend, detect_session
    print(f"Session: {detect_session()}")
    print(f"Backend policy: {', '.join(backend_candidates(args.backend))}")
    if not args.live:
        print("Inspection only: no backend constructed, no portal prompt or input. Availability is NOT verified.")
        return 0
    instance = None
    try:
        instance = create_mouse_backend(args.backend)
        check_interface(instance)
        live_check(instance)
        print(f"Live checks completed: {instance.name}")
        return 0
    except Exception as exc:
        print(f"Live check failed: {exc}")
        return 1
    finally:
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
