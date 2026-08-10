"""
coord_recorder.py - Lightweight coordinate + keystroke recorder.

Captures raw input events WITHOUT resolving UIA elements at click time:
  - Mouse clicks: absolute x,y, button, plus foreground window context
    (title, process name, window rect) so coordinates can later be
    resolved window-relatively against the screen repository.
  - Keystrokes: consecutive printable characters are coalesced into a
    single "keys" text event; special keys (ENTER, TAB, F5...) are
    recorded as separate "key" events.

A pause hotkey (default Ctrl+Shift+F12) toggles capture on/off during
recording so sensitive input can be skipped entirely.

All events are delivered to the on_event callback FROM HOOK THREADS -
GUI consumers must marshal to the tkinter main loop themselves.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from src.recording.keyboard_hook import KeyboardHook
from src.repository.screen_db import RecordedEvent
from src.utils.mouse_hook import MouseHook
from src.utils.win_helpers import (
    get_process_id_from_hwnd,
    get_process_name,
    get_window_at_point,
    get_window_rect,
    get_window_text,
)

import ctypes

_user32 = ctypes.windll.user32
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetAncestor.restype = ctypes.c_void_p
_user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]

GA_ROOT = 2

VK_F12 = 0x7B
VK_CONTROL = 0x11
VK_SHIFT = 0x10

# Flush coalesced text if no keystroke arrives within this window
_TEXT_FLUSH_TIMEOUT = 2.0


def _foreground_window_context() -> tuple[str, str, tuple[int, int, int, int], int]:
    """Return (title, process_name, window_rect, pid) of the foreground window."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return "", "", (0, 0, 0, 0), 0
        return _window_context_from_hwnd(hwnd)
    except Exception:
        return "", "", (0, 0, 0, 0), 0


def _window_context_at_point(
    x: int, y: int
) -> tuple[str, str, tuple[int, int, int, int], int]:
    """Return (title, process_name, window_rect, pid) of the top-level window
    under the given screen point.

    Clicks must be attributed to the window actually being clicked, NOT the
    foreground window: at WM_LBUTTONDOWN time focus has not yet transferred,
    so the foreground window is still the *previously* active one (e.g. a
    click on a target app's title bar would be attributed to UIATools, and a
    taskbar click would be attributed to the target app).
    """
    try:
        hwnd = get_window_at_point(x, y)
        if not hwnd:
            return "", "", (0, 0, 0, 0), 0
        return _window_context_from_hwnd(hwnd)
    except Exception:
        return "", "", (0, 0, 0, 0), 0


def _window_context_from_hwnd(
    hwnd: int,
) -> tuple[str, str, tuple[int, int, int, int], int]:
    root_hwnd = _user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    title = get_window_text(root_hwnd)
    pid = get_process_id_from_hwnd(root_hwnd)
    process = get_process_name(pid)
    rect = get_window_rect(root_hwnd)
    return title, process, rect, pid


class CoordRecorder:
    """
    Records raw clicks and keystrokes with window context.

    Usage:
        rec = CoordRecorder(on_event=my_callback)   # callback from hook threads!
        rec.start()
        ...
        rec.stop()
        events = rec.events
    """

    def __init__(
        self,
        on_event: Optional[Callable[[RecordedEvent], None]] = None,
        on_pause_toggle: Optional[Callable[[bool], None]] = None,
    ):
        self._on_event = on_event
        self._on_pause_toggle = on_pause_toggle
        self._events: list[RecordedEvent] = []
        self._lock = threading.Lock()
        self._recording = False
        self._paused = False
        self._start_time = 0.0
        self._seq = 0
        self._own_pid = os.getpid()

        # Text coalescing state
        self._pending_text: list[str] = []
        self._pending_text_started = 0.0
        self._pending_text_context: tuple[str, str, tuple[int, int, int, int]] = (
            "", "", (0, 0, 0, 0),
        )
        self._last_key_time = 0.0
        self._flush_timer: Optional[threading.Timer] = None

        self._mouse_hook: Optional[MouseHook] = None
        self._keyboard_hook: Optional[KeyboardHook] = None

    # ── Public API ────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def events(self) -> list[RecordedEvent]:
        with self._lock:
            return list(self._events)

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    def start(self):
        """Start capturing clicks and keystrokes."""
        if self._recording:
            return
        with self._lock:
            self._events.clear()
            self._seq = 0
        self._pending_text.clear()
        self._recording = True
        self._paused = False
        self._start_time = time.time()

        self._mouse_hook = MouseHook(self._on_click, require_ctrl=False)
        self._mouse_hook.start()
        self._keyboard_hook = KeyboardHook(self._on_key)
        self._keyboard_hook.start()

    def stop(self):
        """Stop capturing and flush pending text."""
        if not self._recording:
            return
        self._flush_pending_text()
        self._recording = False
        if self._mouse_hook:
            self._mouse_hook.stop()
            self._mouse_hook = None
        if self._keyboard_hook:
            self._keyboard_hook.stop()
            self._keyboard_hook = None
        self._cancel_flush_timer()

    def toggle_pause(self):
        """Pause/resume capture (used by the pause hotkey and GUI)."""
        self._flush_pending_text()
        self._paused = not self._paused
        if self._on_pause_toggle:
            try:
                self._on_pause_toggle(self._paused)
            except Exception:
                pass

    def remove_event(self, seq: int):
        """Delete an event by sequence number."""
        with self._lock:
            self._events = [ev for ev in self._events if ev.seq != seq]

    def redact_event(self, seq: int):
        """Replace an event's text with a redaction marker."""
        with self._lock:
            for ev in self._events:
                if ev.seq == seq:
                    ev.text = "***REDACTED***"
                    ev.redacted = True
                    break

    def clear(self):
        """Remove all recorded events."""
        with self._lock:
            self._events.clear()
            self._seq = 0

    # ── Hook callbacks (run on hook threads) ─────────────────

    def _on_click(self, x: int, y: int, button: str):
        if not self._recording or self._paused:
            return

        # Attribute the click to the window UNDER THE CURSOR (not the
        # foreground window - focus hasn't transferred yet at button-down).
        title, process, rect, pid = _window_context_at_point(x, y)

        # Ignore clicks on UIATools itself
        if pid == self._own_pid:
            return

        # A click ends any pending typed-text run
        self._flush_pending_text()

        self._append_event(
            RecordedEvent(
                seq=0,  # assigned in _append_event
                t_offset=time.time() - self._start_time,
                event_type="click",
                x=x,
                y=y,
                button=button,
                window_title=title,
                process_name=process,
                window_rect=rect,
            )
        )

    def _on_key(self, vk: int, char: str, key_name: str):
        if not self._recording:
            return

        # Pause hotkey: Ctrl+Shift+F12 (works even while paused)
        if vk == VK_F12:
            ctrl = _user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
            shift = _user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
            if ctrl and shift:
                self.toggle_pause()
                return

        if self._paused:
            return

        title, process, rect, pid = _foreground_window_context()
        if pid == self._own_pid:
            return

        if char:
            # Coalesce printable characters
            if not self._pending_text:
                self._pending_text_started = time.time() - self._start_time
                self._pending_text_context = (title, process, rect)
            self._pending_text.append(char)
            self._last_key_time = time.time()
            self._schedule_flush_timer()
        elif key_name:
            if key_name == "BACKSPACE" and self._pending_text:
                self._pending_text.pop()
                return
            # Special key ends the pending run and is recorded separately
            self._flush_pending_text()
            self._append_event(
                RecordedEvent(
                    seq=0,
                    t_offset=time.time() - self._start_time,
                    event_type="key",
                    vk_name=key_name,
                    window_title=title,
                    process_name=process,
                    window_rect=rect,
                )
            )

    # ── Text coalescing ──────────────────────────────────────

    def _schedule_flush_timer(self):
        self._cancel_flush_timer()
        self._flush_timer = threading.Timer(_TEXT_FLUSH_TIMEOUT, self._flush_pending_text)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _cancel_flush_timer(self):
        if self._flush_timer:
            try:
                self._flush_timer.cancel()
            except Exception:
                pass
            self._flush_timer = None

    def _flush_pending_text(self):
        """Emit the coalesced typed-text run as one 'keys' event."""
        self._cancel_flush_timer()
        if not self._pending_text:
            return
        text = "".join(self._pending_text)
        self._pending_text = []
        title, process, rect = self._pending_text_context
        self._append_event(
            RecordedEvent(
                seq=0,
                t_offset=self._pending_text_started,
                event_type="keys",
                text=text,
                window_title=title,
                process_name=process,
                window_rect=rect,
            )
        )

    def _append_event(self, event: RecordedEvent):
        with self._lock:
            self._seq += 1
            event.seq = self._seq
            self._events.append(event)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass
