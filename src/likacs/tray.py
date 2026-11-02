"""Windows 10/11 system-tray integration using only ctypes + the standard library.

* Live hover tooltip (Windows caps szTip at 127 characters).
* Left-click shows the window; right-click opens a full live status menu.
* Menu includes a clickable likaapps.com item, About, updates, Show/Hide, Exit.
* Closing the window minimizes cleanly to the notification area.

On non-Windows systems a no-op tray is used so the rest of the app remains
importable and testable in CI (and for the headless --self-test mode).
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

from .branding import TRAY_PREFIX, fit_tray_tooltip
from .icon import write_icon_file
from .protocol import MAX_TOOLTIP_CHARS
from .util import IS_WINDOWS

MenuItems = Callable[[], list[dict[str, Any]]]
Logger = Callable[[str], None]


class NullTray:
    """Cross-platform fallback (also used by --self-test)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.logger: Logger = kwargs.get("logger") or (lambda _msg: None)
        self._stop = threading.Event()
        self.last_tooltip = ""

    def start(self) -> None:
        self.logger("System tray is Windows-only; running with tray disabled")

    def update(self) -> None:
        get_tooltip = getattr(self, "get_tooltip", None)
        if callable(get_tooltip):
            self.last_tooltip = get_tooltip()

    def notify(self, title: str, message: str) -> None:
        self.logger(f"{title}: {message}")

    def stop(self) -> None:
        self._stop.set()


if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    # ctypes.wintypes has NO HCURSOR attribute (verified on Python 3.11); it is
    # simply a HANDLE typedef in winuser.h. Referencing the missing attribute
    # here crashed every Windows GUI .exe at import time. Use a safe alias so
    # the WNDCLASSW structure always builds, on every Python/Tk build.
    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
    NIIF_INFO = 0x1
    WM_APP, WM_COMMAND, WM_QUIT, WM_NULL = 0x8000, 0x0111, 0x0012, 0x0000
    WM_TRAY = WM_APP + 1
    WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
    MF_STRING, MF_GRAYED, MF_BYPOSITION, MF_SEPARATOR = 0x0, 0x1, 0x400, 0x800
    TPM_LEFTALIGN, TPM_RIGHTBUTTON = 0x0, 0x2
    IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
    HWND_MESSAGE = -3

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", HCURSOR), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    # Explicit signatures prevent handle truncation on 64-bit Python.
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HICON
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.InsertMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT,
                                   wintypes.UINT, wintypes.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      ctypes.c_void_p]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    class WindowsTray:
        """Real Windows notification-area icon."""

        def __init__(self, get_tooltip: Callable[[], str], get_menu_items: MenuItems,
                     on_command: Callable[[str], None], on_show: Callable[[], None],
                     logger: Logger | None = None) -> None:
            self.get_tooltip = get_tooltip
            self.get_menu_items = get_menu_items
            self.on_command = on_command
            self.on_show = on_show
            self.logger = logger or (lambda _msg: None)
            self._stop = threading.Event()
            self._hwnd: int | None = None
            self._hicon: int | None = None
            self._thread_id = 0
            self._loop_thread: threading.Thread | None = None
            self._refresh_thread: threading.Thread | None = None
            self._menu_ids: dict[int, str] = {}
            self._wnd_proc: Any = None
            self._lock = threading.Lock()
            self.last_tooltip = ""

        # ------------------------------------------------------------ internals
        def _icon_data(self) -> NOTIFYICONDATAW:
            data = NOTIFYICONDATAW()
            data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            data.hWnd = self._hwnd
            data.uID = 1
            data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            data.uCallbackMessage = WM_TRAY
            data.hIcon = self._hicon
            data.szTip = fit_tray_tooltip([], MAX_TOOLTIP_CHARS)
            return data

        def _wnd_proc_impl(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    try:
                        self.on_show()
                    except Exception as exc:
                        self.logger(f"tray show error: {exc}")
                elif event == WM_RBUTTONUP:
                    self._show_menu(hwnd)
                return 0
            if msg == WM_COMMAND:
                command = self._menu_ids.get(wparam & 0xFFFF)
                if command:
                    try:
                        self.on_command(command)
                    except Exception as exc:
                        self.logger(f"tray command error: {exc}")
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _message_loop(self) -> None:
            self._thread_id = kernel32.GetCurrentThreadId()
            message = wintypes.MSG()
            while not self._stop.is_set():
                try:
                    result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                except Exception as exc:
                    self.logger(f"tray message loop stopped: {exc}")
                    return
                if result in (0, -1):
                    return
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))

        def _refresh_loop(self) -> None:
            while not self._stop.wait(2.0):
                self.update()

        def _show_menu(self, hwnd: int) -> None:
            try:
                items = self.get_menu_items() or []
            except Exception as exc:
                self.logger(f"tray menu error: {exc}")
                items = []
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            self._menu_ids.clear()
            next_id = 1000
            position = 0
            for item in items:
                if item.get("separator"):
                    user32.InsertMenuW(menu, position, MF_BYPOSITION | MF_SEPARATOR, 0, None)
                    position += 1
                    continue
                label = str(item.get("label", ""))[:96]
                command = item.get("id")
                flags = MF_BYPOSITION | MF_STRING
                if not command or item.get("disabled"):
                    user32.InsertMenuW(menu, position, flags | MF_GRAYED, 0, label)
                else:
                    self._menu_ids[next_id] = str(command)
                    user32.InsertMenuW(menu, position, flags, next_id, label)
                    next_id += 1
                position += 1
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(hwnd)
            user32.TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_RIGHTBUTTON,
                                  point.x, point.y, 0, hwnd, None)
            user32.PostMessageW(hwnd, WM_NULL, 0, 0)
            user32.DestroyMenu(menu)

        # -------------------------------------------------------------- public
        def start(self) -> None:
            if self._hwnd is not None:
                return
            icon_path = write_icon_file()
            self._hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                            LR_LOADFROMFILE | LR_DEFAULTSIZE)
            self._wnd_proc = WNDPROC(self._wnd_proc_impl)
            class_name = "LIKAcsTrayWindow"
            wnd_class = WNDCLASSW()
            wnd_class.style = 0
            wnd_class.lpfnWndProc = self._wnd_proc
            wnd_class.hInstance = kernel32.GetModuleHandleW(None)
            wnd_class.lpszClassName = class_name
            if not user32.RegisterClassW(ctypes.byref(wnd_class)):
                self.logger("tray: RegisterClassW failed (class may already exist)")
            self._hwnd = user32.CreateWindowExW(
                0, class_name, "LIKAcs Tray", 0, 0, 0, 0, 0,
                wintypes.HWND(HWND_MESSAGE), None, wnd_class.hInstance, None,
            )
            if not self._hwnd:
                self._hwnd = None
                self.logger("tray: could not create message window")
                return
            data = self._icon_data()
            data.szTip = self.get_tooltip()[:127]
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
                self.logger("tray: Shell_NotifyIconW(NIM_ADD) failed")
            self._loop_thread = threading.Thread(target=self._message_loop, name="likacs-tray", daemon=True)
            self._refresh_thread = threading.Thread(target=self._refresh_loop, name="likacs-tray-tip", daemon=True)
            self._loop_thread.start()
            self._refresh_thread.start()
            self.logger("System tray icon active (hover for live room status)")

        def update(self) -> None:
            if self._hwnd is None:
                return
            try:
                text = self.get_tooltip()
            except Exception:
                return
            self.last_tooltip = text
            with self._lock:
                data = self._icon_data()
                data.uFlags = NIF_TIP
                data.szTip = text[:127]
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

        def notify(self, title: str, message: str) -> None:
            if self._hwnd is None:
                return
            with self._lock:
                data = self._icon_data()
                data.uFlags = NIF_INFO
                data.szInfoTitle = title[:63]
                data.szInfo = message[:255]
                data.dwInfoFlags = NIIF_INFO
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

        def stop(self) -> None:
            self._stop.set()
            if self._hwnd is not None:
                with self._lock:
                    data = self._icon_data()
                    data.uFlags = 0
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                if self._thread_id:
                    user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
                if self._hicon:
                    try:
                        user32.DestroyIcon(self._hicon)
                    except Exception:
                        pass
                self._hwnd = None
            for thread in (self._loop_thread, self._refresh_thread):
                if thread:
                    thread.join(timeout=1.5)

else:
    WindowsTray = NullTray  # type: ignore[assignment,misc]


def create_tray(get_tooltip: Callable[[], str], get_menu_items: MenuItems,
                on_command: Callable[[str], None], on_show: Callable[[], None],
                logger: Logger | None = None):
    """Factory: real tray on Windows, harmless no-op elsewhere."""
    tray_class = WindowsTray if IS_WINDOWS else NullTray
    tray = tray_class(get_tooltip, get_menu_items, on_command, on_show, logger=logger)
    if isinstance(tray, NullTray):
        tray.get_tooltip = get_tooltip  # kept so NullTray.update() reflects live status
    return tray
