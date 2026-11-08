"""libei sender using an asynchronous XDG RemoteDesktop portal session.

ABI checked against /usr/include/libei-1.0/libei.h. All libei operations
(including dispatch) are serialized; retained devices have explicit references.
"""
import ctypes
import os
import threading
import time
import uuid

from .base import Button, MouseBackend

EI_CAP_POINTER = 1
EI_CAP_POINTER_ABSOLUTE = 2
EI_CAP_SCROLL = 16
EI_CAP_BUTTON = 32
_BIND_CAPS = (1, 2, 16, 32)
_WL_BTN = {Button.LEFT: 0x110, Button.RIGHT: 0x111, Button.MIDDLE: 0x112}


class LibeiBackend(MouseBackend):
    name = "libei"

    def __init__(self, connect_timeout=5.0, portal_timeout=30.0):
        self._portal_timeout = float(portal_timeout)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._devices = {}
        self._resumed = set()
        self._down = {}
        self._seats = set()
        self._ei = None
        self._fd = None
        self._session = None
        self._bus = None
        self._thread = None
        self._closed = False
        self._error = None
        try:
            self._lib = ctypes.CDLL("libei.so.1")
            self._bind_signatures()
            self._fd = self._portal_socket_fd()
            self._setup_ei()
            self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
            self._thread.start()
            if not self._ready.wait(float(connect_timeout)):
                raise RuntimeError(self._error or "no resumed relative pointer device")
        except BaseException:
            # Ctrl-C during a permission prompt must close partial sessions too.
            self.close()
            raise

    def _setup_ei(self):
        self._ei = self._lib.ei_new_sender(None)
        if not self._ei:
            raise RuntimeError("ei_new_sender failed")
        # ei_setup_backend_fd takes ownership; context teardown closes the fd.
        fd, self._fd = self._fd, None
        rc = self._lib.ei_setup_backend_fd(self._ei, fd)
        if rc:
            raise RuntimeError(f"ei_setup_backend_fd failed: {rc}")

    def _bind_signatures(self):
        p, u, d = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_double
        signatures = {
            "ei_new_sender": (p, [p]), "ei_unref": (p, [p]),
            "ei_setup_backend_fd": (ctypes.c_int, [p, ctypes.c_int]),
            "ei_dispatch": (None, [p]), "ei_get_event": (p, [p]),
            "ei_event_unref": (p, [p]), "ei_event_get_type": (ctypes.c_int, [p]),
            "ei_event_get_device": (p, [p]), "ei_event_get_seat": (p, [p]),
            "ei_device_ref": (p, [p]), "ei_device_unref": (p, [p]),
            "ei_device_has_capability": (ctypes.c_bool, [p, ctypes.c_int]),
            "ei_seat_bind_capabilities": (None, [p]),
            "ei_device_start_emulating": (None, [p, u]),
            "ei_device_pointer_motion": (None, [p, d, d]),
            "ei_device_pointer_motion_absolute": (None, [p, d, d]),
            "ei_device_button_button": (None, [p, u, ctypes.c_bool]),
            "ei_device_scroll_discrete": (None, [p, ctypes.c_int32, ctypes.c_int32]),
            "ei_device_frame": (None, [p, ctypes.c_uint64]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self._lib, name)
            fn.restype, fn.argtypes = result, args

    def _portal_request(self, method, signature, values, options):
        Gio, GLib, bus = self._Gio, self._GLib, self._bus
        token = "handmouse_" + uuid.uuid4().hex
        options = dict(options, handle_token=GLib.Variant("s", token))
        sender = bus.get_unique_name()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        response = []
        context = GLib.MainContext.new()
        context.push_thread_default()
        subscription = None
        try:
            def received(connection, sender, object_path, interface, signal, parameters):
                response.append(parameters.unpack())
            subscription = bus.signal_subscribe(
                "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
                "Response", path, None, Gio.DBusSignalFlags.NONE, received)
            reply = bus.call_sync(
                "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.RemoteDesktop", method,
                GLib.Variant(signature, (*values, options)), GLib.VariantType("(o)"),
                Gio.DBusCallFlags.NONE, int(self._portal_timeout * 1000), None)
            actual = reply.unpack()[0]
            if actual != path:
                raise RuntimeError(f"portal returned unexpected request path: {actual}")
            deadline = time.monotonic() + self._portal_timeout
            while not response:
                while context.pending():
                    context.iteration(False)
                if self._stop.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError(f"portal {method} cancelled or timed out")
                self._stop.wait(0.005)
            code, results = response[0]
            if code:
                raise RuntimeError(f"portal {method} rejected (response {code})")
            return results
        except BaseException:
            try:
                bus.call_sync("org.freedesktop.portal.Desktop", path,
                              "org.freedesktop.portal.Request", "Close", None, None,
                              Gio.DBusCallFlags.NONE, 1000, None)
            except Exception:
                pass
            raise
        finally:
            if subscription is not None:
                bus.signal_unsubscribe(subscription)
            context.pop_thread_default()

    def _portal_socket_fd(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        self._Gio, self._GLib = Gio, GLib
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Predict the session path as well, so timeout/cancellation can close
        # a session created before its Response was delivered.
        token = "handmouse_" + uuid.uuid4().hex
        sender = self._bus.get_unique_name()[1:].replace(".", "_")
        self._session = f"/org/freedesktop/portal/desktop/session/{sender}/{token}"
        result = self._portal_request("CreateSession", "(a{sv})", (),
                                      {"session_handle_token": GLib.Variant("s", token)})
        handle = result["session_handle"]
        self._session = handle.unpack() if hasattr(handle, "unpack") else handle
        self._portal_request("SelectDevices", "(oa{sv})", (self._session,),
                             {"types": GLib.Variant("u", 2)})
        self._portal_request("Start", "(osa{sv})", (self._session, ""), {})
        reply, fd_list = self._bus.call_with_unix_fd_list_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.RemoteDesktop", "ConnectToEIS",
            GLib.Variant("(oa{sv})", (self._session, {})), GLib.VariantType("(h)"),
            Gio.DBusCallFlags.NONE, int(self._portal_timeout * 1000), None, None)
        # h is an index, not an OS fd. get() returns an owned duplicate.
        return fd_list.get(reply.unpack()[0])

    def _handle_event(self, event):
        lib = self._lib
        kind = lib.ei_event_get_type(event)
        if kind == 3:
            seat = lib.ei_event_get_seat(event)
            if seat and seat not in self._seats:
                lib.ei_seat_bind_capabilities(ctypes.c_void_p(seat),
                    *(ctypes.c_int(c) for c in _BIND_CAPS), ctypes.c_void_p())
                self._seats.add(seat)
        elif kind == 4:
            self._seats.discard(lib.ei_event_get_seat(event))
        elif kind in (5, 6, 7, 8):
            device = lib.ei_event_get_device(event)
            if kind == 5 and device and device not in self._devices:
                self._devices[device] = {c for c in _BIND_CAPS
                                        if lib.ei_device_has_capability(device, c)}
                lib.ei_device_ref(device)
            elif kind == 8 and device in self._devices:
                lib.ei_device_start_emulating(device, 0)
                self._resumed.add(device)
            elif kind in (6, 7):
                self._resumed.discard(device)
                self._down = {b: d for b, d in self._down.items() if d != device}
                if kind == 6 and device in self._devices:
                    del self._devices[device]
                    lib.ei_device_unref(device)
        elif kind == 2:
            self._down.clear()
            self._resumed.clear()
            self._error = "libei disconnected"
            self._stop.set()
        if self._device_for(EI_CAP_POINTER):
            self._ready.set()
        else:
            self._ready.clear()

    def _dispatch_loop(self):
        try:
            while not self._stop.is_set():
                with self._lock:
                    self._lib.ei_dispatch(self._ei)
                    while True:
                        event = self._lib.ei_get_event(self._ei)
                        if not event:
                            break
                        try:
                            self._handle_event(event)
                        finally:
                            self._lib.ei_event_unref(event)
                self._stop.wait(0.005)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._down.clear()
                self._resumed.clear()
                self._ready.clear()
                self._stop.set()

    def _device_for(self, capability):
        return next((d for d in self._resumed
                     if capability in self._devices[d]), None)

    def _frame(self, device):
        self._lib.ei_device_frame(device, time.monotonic_ns() // 1000)

    def _send(self, capability, method, *args):
        with self._lock:
            if self._closed:
                return
            device = self._device_for(capability)
            if device:
                getattr(self._lib, method)(device, *args)
                self._frame(device)

    def move_relative(self, dx, dy):
        self._send(EI_CAP_POINTER, "ei_device_pointer_motion", float(dx), float(dy))

    def move_absolute(self, x, y):
        self._send(EI_CAP_POINTER_ABSOLUTE, "ei_device_pointer_motion_absolute", float(x), float(y))

    def scroll(self, dx, dy):
        # libei discrete units are 1/120 of a wheel detent; positive is down/right.
        self._send(EI_CAP_SCROLL, "ei_device_scroll_discrete", round(dx * 120), round(dy * 120))

    def button_down(self, button):
        with self._lock:
            device = self._device_for(EI_CAP_BUTTON)
            if self._closed or not device or button in self._down:
                return
            self._lib.ei_device_button_button(device, _WL_BTN[button], True)
            self._frame(device)
            self._down[button] = device

    def button_up(self, button):
        with self._lock:
            device = self._down.get(button)
            if device in self._resumed:
                self._lib.ei_device_button_button(device, _WL_BTN[button], False)
                self._frame(device)
            self._down.pop(button, None)

    def is_button_down(self, button):
        with self._lock:
            return button in self._down

    def close(self):
        with self._lock:
            if self._closed:
                return
            try:
                self.release_all()
            except Exception:
                # Transport failure must not prevent resource/session cleanup.
                pass
            finally:
                self._closed = True
                self._down.clear()
                self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            for device in self._devices:
                self._lib.ei_device_unref(device)
            self._devices.clear()
            self._resumed.clear()
            self._ready.clear()
            if self._ei:
                self._lib.ei_unref(self._ei)
                self._ei = None
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
        if self._session and self._bus:
            try:
                self._bus.call_sync("org.freedesktop.portal.Desktop", self._session,
                    "org.freedesktop.portal.Session", "Close", None, None,
                    self._Gio.DBusCallFlags.NONE, 1000, None)
            except Exception:
                pass
            finally:
                self._session = None
