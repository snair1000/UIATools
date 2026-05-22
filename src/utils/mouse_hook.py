"""
mouse_hook.py - Global mouse hook for click-to-inspect functionality.

Uses ctypes to install a low-level mouse hook that captures click
coordinates without interfering with normal mouse operation.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from typing import Callable, Optional

# Windows constants
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
HC_ACTION = 0

# Callback type for mouse hook
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


# ---------- 64-bit safe Win32 function declarations ----------
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_kernel32.GetModuleHandleW.restype = ctypes.c_void_p
_kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]

_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.wintypes.DWORD,
]

_user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

_user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM  # LRESULT
_user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]

_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

_user32.GetMessageW.argtypes = [
    ctypes.POINTER(ctypes.wintypes.MSG), ctypes.wintypes.HWND,
    ctypes.wintypes.UINT, ctypes.wintypes.UINT,
]

_user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]

_user32.PostThreadMessageW.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]


class MouseHook:
    """
    Global low-level mouse hook that captures click coordinates.

    Usage:
        def on_click(x, y, button):
            print(f"Clicked at ({x}, {y}) with {button}")

        hook = MouseHook(on_click)
        hook.start()
        # ... later ...
        hook.stop()
    """

    def __init__(self, callback: Callable[[int, int, str], None]):
        """
        Args:
            callback: Called with (x, y, button_name) when a mouse click is detected.
                      button_name is "left" or "right".
        """
        self._callback = callback
        self._hook_handle: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Install the mouse hook on a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._hook_thread, daemon=True)
        self._thread.start()

    def stop(self):
        """Remove the mouse hook."""
        self._running = False
        if self._hook_handle:
            try:
                _user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                pass
            self._hook_handle = None

        # Post a quit message to the hook thread's message loop
        if self._thread and self._thread.is_alive():
            try:
                tid = self._thread.ident
                if tid:
                    _user32.PostThreadMessageW(
                        tid, 0x0012, 0, 0  # WM_QUIT
                    )
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    def _hook_thread(self):
        """Thread function that installs the hook and runs a message loop."""
        import sys

        @HOOKPROC
        def _low_level_mouse_proc(nCode, wParam, lParam):
            if nCode == HC_ACTION and self._running:
                ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x = ms.pt.x
                y = ms.pt.y

                # Only inspect when Ctrl key is held down (0x11 = VK_CONTROL)
                ctrl_state = _user32.GetAsyncKeyState(0x11)
                ctrl_pressed = (ctrl_state & 0x8000) != 0

                if wParam == WM_LBUTTONDOWN and ctrl_pressed:
                    try:
                        self._callback(x, y, "left")
                    except Exception:
                        pass
                elif wParam == WM_RBUTTONDOWN and ctrl_pressed:
                    try:
                        self._callback(x, y, "right")
                    except Exception:
                        pass

            return _user32.CallNextHookEx(
                self._hook_handle, nCode, wParam, lParam
            )

        # Keep a reference to prevent garbage collection
        self._hook_proc = _low_level_mouse_proc

        hmod = _kernel32.GetModuleHandleW(None)
        self._hook_handle = _user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            hmod,
            0,
        )

        if not self._hook_handle:
            print(f"[UIATools] FAILED to install mouse hook (hmod={hmod:#018x})", file=sys.stderr)
            self._running = False
            return

        print(f"[UIATools] Mouse hook installed (handle={self._hook_handle:#018x})", file=sys.stderr)

        # Message loop to keep the hook alive
        msg = ctypes.wintypes.MSG()
        while self._running:
            result = _user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            )
            if result <= 0:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        if self._hook_handle:
            _user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
        self._running = False
