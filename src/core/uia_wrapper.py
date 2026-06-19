"""
uia_wrapper.py - Low-level UI Automation COM wrapper.

Provides a thin abstraction over the Windows UIAutomation COM interface
using comtypes and the uiautomation library. This is the foundation layer
that all other core modules build upon.
"""

import ctypes
import ctypes.wintypes
from dataclasses import dataclass, field
from typing import Optional

import uiautomation as auto


@dataclass
class ElementInfo:
    """Snapshot of a UIA element's key properties."""

    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    control_type: str = ""
    control_type_name: str = ""
    localized_control_type: str = ""
    bounding_rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    center_x: int = 0
    center_y: int = 0
    is_enabled: bool = False
    is_offscreen: bool = False
    is_keyboard_focusable: bool = False
    has_keyboard_focus: bool = False
    process_id: int = 0
    framework_id: str = ""
    runtime_id: str = ""
    path: str = ""
    native_window_handle: int = 0
    value: str = ""
    access_key: str = ""
    accelerator_key: str = ""
    help_text: str = ""
    item_type: str = ""
    item_status: str = ""
    extra_properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for display / export."""
        d = {
            "Name": self.name,
            "AutomationId": self.automation_id,
            "ClassName": self.class_name,
            "ControlType": self.control_type_name,
            "LocalizedControlType": self.localized_control_type,
            "BoundingRectangle": f"{self.bounding_rect}",
            "CenterX": self.center_x,
            "CenterY": self.center_y,
            "IsEnabled": self.is_enabled,
            "IsOffscreen": self.is_offscreen,
            "IsKeyboardFocusable": self.is_keyboard_focusable,
            "HasKeyboardFocus": self.has_keyboard_focus,
            "ProcessId": self.process_id,
            "FrameworkId": self.framework_id,
            "RuntimeId": self.runtime_id,
            "Path": self.path,
            "NativeWindowHandle": hex(self.native_window_handle) if self.native_window_handle else "",
            "Value": self.value,
            "AccessKey": self.access_key,
            "AcceleratorKey": self.accelerator_key,
            "HelpText": self.help_text,
            "ItemType": self.item_type,
            "ItemStatus": self.item_status,
        }
        d.update(self.extra_properties)
        return d


def get_root_element() -> auto.Control:
    """Return the UIA root (Desktop) element."""
    return auto.GetRootControl()


def control_to_element_info(ctrl: auto.Control, path: str = "") -> ElementInfo:
    """
    Extract an ElementInfo snapshot from a uiautomation Control.
    Wraps each property access in a try/except so one failing
    property doesn't crash the whole inspector.
    """
    info = ElementInfo()
    info.path = path

    def _safe(func, default=""):
        try:
            return func()
        except Exception:
            return default

    info.name = _safe(lambda: ctrl.Name, "")
    info.automation_id = _safe(lambda: ctrl.AutomationId, "")
    info.class_name = _safe(lambda: ctrl.ClassName, "")
    info.control_type = _safe(lambda: ctrl.ControlType, 0)
    info.control_type_name = _safe(lambda: ctrl.ControlTypeName, "")
    info.localized_control_type = _safe(lambda: ctrl.LocalizedControlType, "")

    rect = _safe(lambda: ctrl.BoundingRectangle, None)
    if rect:
        info.bounding_rect = (rect.left, rect.top, rect.right, rect.bottom)
        info.center_x = (rect.left + rect.right) // 2
        info.center_y = (rect.top + rect.bottom) // 2

    info.is_enabled = _safe(lambda: ctrl.IsEnabled, False)
    info.is_offscreen = _safe(lambda: ctrl.IsOffscreen, True)
    info.is_keyboard_focusable = _safe(lambda: ctrl.IsKeyboardFocusable, False)
    info.has_keyboard_focus = _safe(lambda: ctrl.HasKeyboardFocus, False)
    info.process_id = _safe(lambda: ctrl.ProcessId, 0)
    info.framework_id = _safe(lambda: ctrl.FrameworkId, "")
    info.native_window_handle = _safe(lambda: ctrl.NativeWindowHandle, 0)

    # Value pattern
    try:
        vp = ctrl.GetValuePattern()
        if vp:
            info.value = vp.Value or ""
    except Exception:
        pass

    info.access_key = _safe(lambda: ctrl.AccessKey, "")
    info.accelerator_key = _safe(lambda: ctrl.AcceleratorKey, "")
    info.help_text = _safe(lambda: ctrl.HelpText, "")
    info.item_type = _safe(lambda: ctrl.ItemType, "")
    info.item_status = _safe(lambda: ctrl.ItemStatus, "")

    return info


def element_from_point(x: int, y: int) -> Optional[auto.Control]:
    """Return the deepest UIA element at screen coordinates (x, y)."""
    import sys
    try:
        ctrl = auto.ControlFromPoint(x, y)
        return ctrl
    except Exception as e:
        print(f"[UIATools] ControlFromPoint({x}, {y}) failed: {e}", file=sys.stderr)
        return None


def find_window_by_name(name: str) -> Optional[auto.Control]:
    """Find a top-level window whose Name contains the given string."""
    try:
        root = get_root_element()
        win = root.WindowControl(searchDepth=1, SubName=name)
        if win.Exists(maxSearchSeconds=2):
            return win
    except Exception:
        pass
    return None


def find_window_by_handle(hwnd: int) -> Optional[auto.Control]:
    """Find a UIA control by its native window handle."""
    import sys
    try:
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is not None:
            # Quick verify: try accessing a property
            _ = ctrl.ControlType
            return ctrl
    except Exception as e:
        print(f"[UIATools] ControlFromHandle({hwnd:#010x}) failed: {e}", file=sys.stderr)

    # Fallback: search Desktop children by handle
    try:
        root = get_root_element()
        for child in get_children(root):
            try:
                if child.NativeWindowHandle == hwnd:
                    return child
            except Exception:
                continue
    except Exception as e:
        print(f"[UIATools] Desktop child search fallback failed: {e}", file=sys.stderr)

    return None


def get_children(ctrl: auto.Control) -> list[auto.Control]:
    """Return the immediate children of a UIA control."""
    try:
        return ctrl.GetChildren()
    except Exception:
        return []
