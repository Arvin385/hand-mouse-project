PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PIDFILE := .run/handmouse.pid
LOGFILE := .run/handmouse.log

.PHONY: start stop

start:
	@mkdir -p .run
	@flock -n -o .run/control.lock sh -c '\
		if test -f "$(PIDFILE)" && kill -0 "$$(cat "$(PIDFILE)")" 2>/dev/null; then \
			echo "Hand Mouse already running."; exit 0; \
		fi; \
		HANDMOUSE_MOUSE_BACKEND=auto nohup setsid "$(PYTHON)" -u "$(CURDIR)/vision/src/main.py" \
			</dev/null >>"$(LOGFILE)" 2>&1 & \
		pid=$$!; echo $$pid >"$(PIDFILE)"; \
		sleep 1; \
		if kill -0 $$pid 2>/dev/null; then \
			echo "Hand Mouse launched. Log: $(LOGFILE)"; \
		else \
			rm -f "$(PIDFILE)"; echo "Startup failed. See $(LOGFILE)"; exit 1; \
		fi'

stop:
	@mkdir -p .run
	@flock -n -o .run/control.lock sh -c '\
		if test ! -f "$(PIDFILE)"; then echo "Hand Mouse already stopped."; exit 0; fi; \
		pid=$$(cat "$(PIDFILE)"); \
		if kill -0 "$$pid" 2>/dev/null && \
			tr "\000" "\n" </proc/$$pid/cmdline | grep -Fxq "$(CURDIR)/vision/src/main.py"; then \
			kill -TERM "$$pid"; \
			count=0; \
			while kill -0 "$$pid" 2>/dev/null; do \
				count=$$((count + 1)); \
				if test $$count -ge 15; then echo "Shutdown still pending; retry make stop."; exit 1; fi; \
				sleep 1; \
			done; \
		fi; \
		rm -f "$(PIDFILE)"; echo "Hand Mouse stopped."'
