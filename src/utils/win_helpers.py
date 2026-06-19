"""
win_helpers.py - Windows API helper functions.

Provides utility functions for Windows-specific operations like
getting window info, process names, DPI scaling, etc.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import Optional


def get_cursor_pos() -> tuple[int, int]:
    """Get the current cursor position in screen coordinates."""
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def get_window_at_point(x: int, y: int) -> int:
    """Return the HWND of the window at (x, y)."""
    point = ctypes.wintypes.POINT(x, y)
    hwnd = ctypes.windll.user32.WindowFromPoint(point)
    return hwnd


def get_window_text(hwnd: int) -> str:
    """Get the title text of a window by its HWND."""
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_window_class_name(hwnd: int) -> str:
    """Get the class name of a window by its HWND."""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get the bounding rectangle of a window (left, top, right, bottom)."""
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def get_process_id_from_hwnd(hwnd: int) -> int:
    """Get the process ID of the window owner."""
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_process_name(pid: int) -> str:
    """Get the process name from a process ID."""
    try:
        import psutil

        proc = psutil.Process(pid)
        return proc.name()
    except Exception:
        pass

    # Fallback using ctypes
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size)
            )
            ctypes.windll.kernel32.CloseHandle(handle)
            name = buf.value
            if "\\" in name:
                name = name.rsplit("\\", 1)[1]
            return name
    except Exception:
        pass
    return f"PID:{pid}"


def get_dpi_scale() -> float:
    """Get the system DPI scaling factor."""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:
        return 1.0


def set_foreground_window(hwnd: int) -> bool:
    """Bring a window to the foreground."""
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def enumerate_top_level_windows() -> list[dict]:
    """
    Enumerate all visible top-level windows.
    Returns a list of dicts with hwnd, title, class_name, pid.
    """
    results = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_callback(hwnd, lparam):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            title = get_window_text(hwnd)
            if title:  # skip untitled windows
                results.append(
                    {
                        "hwnd": hwnd,
                        "title": title,
                        "class_name": get_window_class_name(hwnd),
                        "pid": get_process_id_from_hwnd(hwnd),
                    }
                )
        return True

    ctypes.windll.user32.EnumWindows(enum_callback, 0)
    return results
