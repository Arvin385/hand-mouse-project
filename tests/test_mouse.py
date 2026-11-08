"""Safe mouse regressions: fake objects only, never real backend constructors."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

SRC = Path(__file__).resolve().parents[1] / "vision" / "src"
sys.path.insert(0, str(SRC))
from mouse import Button
from mouse.factory import backend_candidates, create_mouse_backend
from mouse.libei_backend import LibeiBackend
from mouse.pynput_backend import PynputBackend
from mouse.uinput_backend import UinputBackend


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_ei():
    backend = object.__new__(LibeiBackend)
    backend._lib = Mock()
    backend._lock = threading.RLock()
    backend._stop = threading.Event()
    backend._ready = threading.Event()
    backend._devices = {}
    backend._resumed = set()
    backend._down = {}
    backend._seats = set()
    backend._closed = False
    backend._ei = 99
    backend._fd = None
    backend._thread = None
    backend._session = None
    backend._bus = None
    backend._error = None
    return backend


def event(backend, kind, device=10, caps=(1, 32, 16)):
    backend._lib.ei_event_get_type.return_value = kind
    backend._lib.ei_event_get_device.return_value = device
    backend._lib.ei_event_get_seat.return_value = 100
    backend._lib.ei_device_has_capability.side_effect = lambda d, c: c in caps
    backend._handle_event(123)


class BackendTests(unittest.TestCase):
    def test_factory_policy_and_override(self):
        with patch.dict('os.environ', {'XDG_SESSION_TYPE': 'wayland', 'HANDMOUSE_MOUSE_BACKEND': 'auto'}, clear=True):
            self.assertEqual(backend_candidates(), ('libei', 'uinput'))
            classes = {'libei': Mock(side_effect=RuntimeError('unavailable')), 'uinput': Mock(return_value=object())}
            with patch('mouse.factory._import_backend', side_effect=classes.__getitem__) as lookup:
                self.assertIs(create_mouse_backend(), classes['uinput'].return_value)
                self.assertEqual([c.args[0] for c in lookup.call_args_list], ['libei', 'uinput'])
            with patch.dict('os.environ', {'HANDMOUSE_MOUSE_BACKEND': 'pynput'}):
                self.assertEqual(backend_candidates(), ('pynput',))
                self.assertEqual(backend_candidates('libei'), ('libei',))
        with self.assertRaises(ValueError):
            backend_candidates('bogus')

    def test_pynput_scroll_and_idempotency(self):
        b = object.__new__(PynputBackend)
        b._controller = Mock()
        b._map = {Button.LEFT: 'left'}
        b._down = set()
        controller = b._controller
        b.scroll(2, 3)
        controller.scroll.assert_called_once_with(2, -3)
        b.button_down(Button.LEFT)
        b.button_down(Button.LEFT)
        b.close()
        b.close()
        controller.press.assert_called_once_with('left')
        controller.release.assert_called_once_with('left')
        self.assertFalse(b.is_button_down(Button.LEFT))

    def test_uinput_scroll(self):
        b = object.__new__(UinputBackend)
        b._ecodes = types.SimpleNamespace(EV_REL=2, REL_WHEEL=8, REL_HWHEEL=6)
        b._device = Mock()
        b.scroll(2, 3)
        self.assertEqual([c.args for c in b._device.write.call_args_list], [(2, 8, -3), (2, 6, 2)])
        # Inspect the capability declaration without constructing a virtual device.
        source = (SRC / 'mouse' / 'uinput_backend.py').read_text()
        self.assertIn('ecodes.REL_HWHEEL: 0', source)

    def test_capability_routing_and_linux_buttons(self):
        b = fake_ei()
        event(b, 5, 10, (1,))
        event(b, 8, 10)
        event(b, 5, 20, (32, 16))
        event(b, 8, 20)
        b.move_relative(4, 5)
        b.button_down(Button.RIGHT)
        b.button_down(Button.RIGHT)
        b.scroll(2, 3)
        b._lib.ei_device_pointer_motion.assert_called_once_with(10, 4., 5.)
        b._lib.ei_device_button_button.assert_called_once_with(20, 0x111, True)
        b._lib.ei_device_scroll_discrete.assert_called_once_with(20, 240, 360)
        b.move_absolute(0, 0)
        b._lib.ei_device_pointer_motion_absolute.assert_not_called()
        self.assertTrue(b._ready.is_set())
        event(b, 7, 20)
        self.assertFalse(b.is_button_down(Button.RIGHT))
        self.assertTrue(b._ready.is_set())
        event(b, 6, 20)
        b._lib.ei_device_unref.assert_called_once_with(20)
        event(b, 7, 10)
        b.move_relative(1, 1)
        self.assertFalse(b._ready.is_set())
        self.assertEqual(b._lib.ei_device_pointer_motion.call_count, 1)
        b.close()
        b.close()
        b._lib.ei_unref.assert_called_once_with(99)

    def test_disconnect_clears_held_state(self):
        b = fake_ei()
        event(b, 5)
        event(b, 8)
        b.button_down(Button.LEFT)
        event(b, 2)
        self.assertFalse(b.is_button_down(Button.LEFT))
        b.button_down(Button.LEFT)
        self.assertEqual(b._lib.ei_device_button_button.call_count, 1)

    def test_facade_tracks_backend_not_stale_flag(self):
        backend = Mock()
        backend.is_button_down.return_value = False
        with patch('mouse.create_mouse_backend', return_value=backend):
            module = load_file('safe_mouse_facade', SRC / 'gestures' / '_mouse.py')
        facade = module.mouse
        facade.left_down()
        self.assertFalse(facade.is_left_down())
        facade.left_down()
        self.assertEqual(backend.button_down.call_count, 2)
        backend.is_button_down.return_value = True
        facade.double_click()
        backend.click.assert_not_called()
        facade.release_all()
        backend.release_all.assert_called_once()

    def test_diagnostic_default_never_constructs_or_injects(self):
        diagnostic = load_file('safe_diagnostic', SRC / 'test_mouse_backend.py')
        with patch('mouse.factory.create_mouse_backend', side_effect=AssertionError('unsafe')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostic.main([]), 0)
        backend = Mock()
        diagnostic.check_interface(backend)
        self.assertEqual(backend.mock_calls, [])
        with patch('mouse.factory.create_mouse_backend', return_value=backend) as factory, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostic.main(['--live', '--backend', 'uinput']), 0)
        factory.assert_called_once_with('uinput')
        backend.close.assert_called_once()


class Variant:
    def __init__(self, signature, value):
        self.signature, self.value = signature, value
    def unpack(self):
        return self.value


class Context:
    def push_thread_default(self): pass
    def pop_thread_default(self): pass
    def pending(self): return False


class PortalTests(unittest.TestCase):
    def portal(self, response=(0, {})):
        b = fake_ei()
        b._portal_timeout = .001
        b._bus = Mock()
        b._bus.get_unique_name.return_value = ':1.42'
        b._GLib = types.SimpleNamespace(Variant=Variant, VariantType=lambda t: t,
                                       MainContext=types.SimpleNamespace(new=Context))
        b._Gio = types.SimpleNamespace(DBusCallFlags=types.SimpleNamespace(NONE=0),
                                      DBusSignalFlags=types.SimpleNamespace(NONE=0))
        def subscribe(*args):
            b.request_path = args[3]
            b.callback = args[-1]
            return 7
        def call(*args):
            if args[3] != 'Close' and response is not None:
                b.callback(None, None, None, None, None, Variant('(ua{sv})', response))
            return Variant('(o)', (b.request_path,))
        b._bus.signal_subscribe.side_effect = subscribe
        b._bus.call_sync.side_effect = call
        return b

    def test_response_subscription_precedes_call(self):
        b = self.portal((0, {'session_handle': '/session/test'}))
        result = b._portal_request('CreateSession', '(a{sv})', (), {})
        self.assertEqual(result['session_handle'], '/session/test')
        self.assertEqual(b._bus.mock_calls[1][0], 'signal_subscribe')
        b._bus.signal_unsubscribe.assert_called_once_with(7)

    def test_denied_and_timeout_close_request(self):
        for response in ((1, {}), (2, {}), None):
            with self.subTest(response=response):
                b = self.portal(response)
                with self.assertRaises((RuntimeError, TimeoutError)):
                    b._portal_request('Start', '(osa{sv})', ('/session', ''), {})
                self.assertEqual(b._bus.call_sync.call_args.args[2:4], ('org.freedesktop.portal.Request', 'Close'))
                b._bus.signal_unsubscribe.assert_called_once_with(7)

    def test_keyboard_interrupt_closes_request(self):
        b = self.portal(None)
        original = b._bus.call_sync.side_effect
        def interrupted(*args):
            if args[3] != 'Close':
                raise KeyboardInterrupt()
            return original(*args)
        b._bus.call_sync.side_effect = interrupted
        with self.assertRaises(KeyboardInterrupt):
            b._portal_request('Start', '(osa{sv})', ('/session', ''), {})
        self.assertEqual(b._bus.call_sync.call_args.args[2:4], ('org.freedesktop.portal.Request', 'Close'))
        b._bus.signal_unsubscribe.assert_called_once_with(7)

    def test_gio_fd_index_and_session_types(self):
        b = fake_ei()
        b._portal_timeout = 1
        bus = Mock()
        bus.get_unique_name.return_value = ':1.42'
        fd_list = Mock()
        fd_list.get.return_value = 73
        bus.call_with_unix_fd_list_sync.return_value = (Variant('(h)', (3,)), fd_list)
        gio = types.SimpleNamespace(bus_get_sync=lambda *a: bus, BusType=types.SimpleNamespace(SESSION=0), DBusCallFlags=types.SimpleNamespace(NONE=0))
        glib = types.SimpleNamespace(Variant=Variant, VariantType=lambda t: t)
        gi = types.ModuleType('gi')
        gi.require_version = Mock()
        repository = types.ModuleType('gi.repository')
        repository.Gio, repository.GLib = gio, glib
        b._portal_request = Mock(side_effect=[{'session_handle': '/session/real'}, {}, {}])
        with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}):
            self.assertEqual(b._portal_socket_fd(), 73)
        fd_list.get.assert_called_once_with(3)
        calls = b._portal_request.call_args_list
        self.assertEqual(calls[1].args[:3], ('SelectDevices', '(oa{sv})', ('/session/real',)))
        self.assertEqual(calls[1].args[3]['types'].unpack(), 2)
        self.assertEqual(calls[2].args[2], ('/session/real', ''))
        b.close()
        self.assertEqual(bus.call_sync.call_args.args[1:4], ('/session/real', 'org.freedesktop.portal.Session', 'Close'))

    def test_transferred_fd_not_closed_twice(self):
        for rc in (0, -1):
            with self.subTest(rc=rc):
                b = fake_ei()
                b._fd = 73
                b._lib.ei_new_sender.return_value = 99
                b._lib.ei_setup_backend_fd.return_value = rc
                with patch('mouse.libei_backend.os.close') as close:
                    if rc:
                        with self.assertRaises(RuntimeError):
                            b._setup_ei()
                    else:
                        b._setup_ei()
                    b.close()
                    b.close()
                close.assert_not_called()
                b._lib.ei_setup_backend_fd.assert_called_once_with(99, 73)
                b._lib.ei_unref.assert_called_once_with(99)

    def test_untransferred_fd_closed_on_context_failure(self):
        b = fake_ei()
        b._fd = 73
        b._lib.ei_new_sender.return_value = None
        with self.assertRaises(RuntimeError):
            b._setup_ei()
        with patch('mouse.libei_backend.os.close') as close:
            b.close()
            b.close()
        close.assert_called_once_with(73)
        b._lib.ei_unref.assert_not_called()

    def test_cancelled_request_is_closed(self):
        b = self.portal(None)
        b._stop.set()
        with self.assertRaises(TimeoutError):
            b._portal_request('Start', '(osa{sv})', ('/session', ''), {})
        self.assertEqual(b._bus.call_sync.call_args.args[2:4], ('org.freedesktop.portal.Request', 'Close'))

    def test_partial_session_and_release_failure_cleanup(self):
        b = self.portal()
        b._session = '/partial/session'
        b.release_all = Mock(side_effect=OSError('transport gone'))
        b.close()
        self.assertIsNone(b._session)
        b._lib.ei_unref.assert_called_once_with(99)
        self.assertEqual(b._bus.call_sync.call_args.args[1:4], ('/partial/session', 'org.freedesktop.portal.Session', 'Close'))

    def test_ctypes_abi_signatures(self):
        import ctypes
        b = fake_ei()
        b._bind_signatures()
        for name in ('ei_dispatch', 'ei_device_frame', 'ei_device_start_emulating', 'ei_seat_bind_capabilities'):
            self.assertIsNone(getattr(b._lib, name).restype)
        self.assertEqual(b._lib.ei_device_scroll_discrete.argtypes, [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32])


if __name__ == '__main__':
    unittest.main()
