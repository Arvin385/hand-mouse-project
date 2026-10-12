from init import initialize
from engine import Engine


def main():
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
        # init.py owns camera + MediaPipe resources
        # --------------------------------------------

        if app is not None:
            app.shutdown()

        print()
        print("Application shutdown complete.")


if __name__ == "__main__":
    main()