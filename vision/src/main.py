import signal

from init import initialize
from engine import Engine
from gestures._mouse import mouse


def _stop(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, _stop)
    app = None

    try:
        # --------------------------------------------
        # Initialize camera + MediaPipe GPU
        # --------------------------------------------

        app = initialize()

        # --------------------------------------------
        # Create engine
        # --------------------------------------------

        engine = Engine(
            app=app,
            debug=True
        )

        # --------------------------------------------
        # Enter interactive loop
        # --------------------------------------------

        engine.run()

    except KeyboardInterrupt:
        print()
        print("Stopped by user.")

    except Exception as exc:
        print()
        print("Application error:")
        print(exc)

        raise

    finally:
        # --------------------------------------------
        # Release the mouse backend (never leave a button held)
        # --------------------------------------------

        try:
            mouse.close()
        except Exception as exc:
            print()
            print(f"Mouse backend cleanup warning: {exc}")

        # --------------------------------------------
        # init.py owns camera + MediaPipe resources
        # --------------------------------------------

        if app is not None:
            app.shutdown()

        print()
        print("Application shutdown complete.")


if __name__ == "__main__":
    main()