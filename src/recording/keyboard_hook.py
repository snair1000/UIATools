"""
keyboard_hook.py - Global low-level keyboard hook for the coordinate recorder.

Mirrors the MouseHook pattern in src/utils/mouse_hook.py:
SetWindowsHookEx(WH_KEYBOARD_LL) on a daemon thread running a
Windows message loop.

The callback receives key-down events only, with the virtual-key code,
a printable character (if the key produces one given current shift state),
and a friendly key name for special keys.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from typing import Callable, Optional

# Windows constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
HC_ACTION = 0

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


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

_user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
_user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]

_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

_user32.GetKeyState.restype = ctypes.c_short
_user32.GetKeyState.argtypes = [ctypes.c_int]

_user32.ToUnicode.restype = ctypes.c_int
_user32.ToUnicode.argtypes = [
    ctypes.wintypes.UINT, ctypes.wintypes.UINT,
    ctypes.POINTER(ctypes.c_byte), ctypes.wintypes.LPWSTR,
    ctypes.c_int, ctypes.wintypes.UINT,
]

_user32.GetKeyboardState.restype = ctypes.wintypes.BOOL
_user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_byte)]

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

# Special key names by virtual-key code
VK_NAMES = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x1B: "ESC",
    0x20: "SPACE", 0x21: "PAGE_UP", 0x22: "PAGE_DOWN", 0x23: "END",
    0x24: "HOME", 0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x2C: "PRINTSCREEN", 0x2D: "INSERT", 0x2E: "DELETE",
    0x5B: "LWIN", 0x5C: "RWIN", 0x5D: "APPS",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5",
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
    0x90: "NUMLOCK", 0x91: "SCROLLLOCK", 0x14: "CAPSLOCK",
    0x10: "SHIFT", 0xA0: "SHIFT", 0xA1: "SHIFT",
    0x11: "CTRL", 0xA2: "CTRL", 0xA3: "CTRL",
    0x12: "ALT", 0xA4: "ALT", 0xA5: "ALT",
}

# Modifier vk codes we do not report as standalone events
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def vk_to_char(vk_code: int, scan_code: int) -> str:
    """Translate a virtual-key code to a printable character (or '')."""
    state = (ctypes.c_byte * 256)()
    if not _user32.GetKeyboardState(state):
        return ""
    # GetKeyboardState in a hook thread may lag; patch shift/caps from async state
    if _user32.GetAsyncKeyState(0x10) & 0x8000:
        state[0x10] = ctypes.c_byte(-128)  # 0x80
    if _user32.GetKeyState(0x14) & 0x0001:
        state[0x14] = ctypes.c_byte(1)
    buf = ctypes.create_unicode_buffer(8)
    n = _user32.ToUnicode(vk_code, scan_code, state, buf, len(buf), 0)
    if n > 0:
        ch = buf.value[:n]
        return ch if ch.isprintable() else ""
    return ""


class KeyboardHook:
    """
    Global low-level keyboard hook that captures key-down events.

    Usage:
        def on_key(vk, char, key_name):
            ...  # char is '' for non-printable keys; key_name for specials

        hook = KeyboardHook(on_key)
        hook.start()
        hook.stop()
    """

    def __init__(self, callback: Callable[[int, str, str], None]):
        """
        Args:
            callback: Called with (vk_code, char, key_name) on key-down.
                      char is the printable character or "".
                      key_name is a friendly name (ENTER, TAB, F5...) or "".
        """
        self._callback = callback
        self._hook_handle: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Install the keyboard hook on a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._hook_thread, daemon=True)
        self._thread.start()

    def stop(self):
        """Remove the keyboard hook."""
        self._running = False
        if self._hook_handle:
            try:
                _user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                pass
            self._hook_handle = None

        if self._thread and self._thread.is_alive():
            try:
                tid = self._thread.ident
                if tid:
                    _user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    def _hook_thread(self):
        """Thread function that installs the hook and runs a message loop."""
        import sys

        @HOOKPROC
        def _low_level_keyboard_proc(nCode, wParam, lParam):
            if nCode == HC_ACTION and self._running:
                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = kb.vkCode
                    if vk not in _MODIFIER_VKS:
                        key_name = VK_NAMES.get(vk, "")
                        char = "" if key_name else vk_to_char(vk, kb.scanCode)
                        try:
                            self._callback(vk, char, key_name)
                        except Exception:
                            pass
            return _user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        self._hook_proc = _low_level_keyboard_proc

        hmod = _kernel32.GetModuleHandleW(None)
        self._hook_handle = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            hmod,
            0,
        )

        if not self._hook_handle:
            print("[UIATools] FAILED to install keyboard hook", file=sys.stderr)
            self._running = False
            return

        msg = ctypes.wintypes.MSG()
        while self._running:
            result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
