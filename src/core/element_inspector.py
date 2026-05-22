"""
element_inspector.py - Inspects detailed properties of a UIA element.

Provides deeper property extraction beyond what uia_wrapper captures
in its base ElementInfo, including pattern support information and
extra UIA properties relevant to Robot Framework locator strategies.
"""

from __future__ import annotations

from typing import Optional

import uiautomation as auto

from src.core.uia_wrapper import ElementInfo, control_to_element_info


# Pattern names to check for availability
_PATTERN_NAMES = [
    "InvokePattern",
    "SelectionPattern",
    "ValuePattern",
    "RangeValuePattern",
    "ScrollPattern",
    "ExpandCollapsePattern",
    "GridPattern",
    "GridItemPattern",
    "MultipleViewPattern",
    "WindowPattern",
    "SelectionItemPattern",
    "DockPattern",
    "TablePattern",
    "TableItemPattern",
    "TextPattern",
    "TogglePattern",
    "TransformPattern",
    "ScrollItemPattern",
    "ItemContainerPattern",
    "VirtualizedItemPattern",
    "SynchronizedInputPattern",
    "LegacyIAccessiblePattern",
]


def inspect_element(
    ctrl: auto.Control,
    path: str = "",
    include_patterns: bool = True,
) -> ElementInfo:
    """
    Perform a deep inspection of a UIA control element.

    Args:
        ctrl: The uiautomation Control to inspect.
        path: The RPA.Windows-style path (e.g., "path:1|3|2").
        include_patterns: If True, probe which UIA patterns the element supports.

    Returns:
        A fully populated ElementInfo dataclass.
    """
    info = control_to_element_info(ctrl, path)

    if include_patterns:
        supported = _get_supported_patterns(ctrl)
        info.extra_properties["SupportedPatterns"] = ", ".join(supported) if supported else "(none)"

    # Try to get toggle state
    try:
        tp = ctrl.GetTogglePattern()
        if tp:
            info.extra_properties["ToggleState"] = str(tp.ToggleState)
    except Exception:
        pass

    # Try to get expand/collapse state
    try:
        ecp = ctrl.GetExpandCollapsePattern()
        if ecp:
            info.extra_properties["ExpandCollapseState"] = str(ecp.ExpandCollapseState)
    except Exception:
        pass

    # Try to get selection state
    try:
        sip = ctrl.GetSelectionItemPattern()
        if sip:
            info.extra_properties["IsSelected"] = str(sip.IsSelected)
    except Exception:
        pass

    # Try to get scroll info
    try:
        sp = ctrl.GetScrollPattern()
        if sp:
            info.extra_properties["HorizontalScrollPercent"] = f"{sp.HorizontalScrollPercent:.1f}%"
            info.extra_properties["VerticalScrollPercent"] = f"{sp.VerticalScrollPercent:.1f}%"
    except Exception:
        pass

    # Window pattern info
    try:
        wp = ctrl.GetWindowPattern()
        if wp:
            info.extra_properties["CanMaximize"] = str(wp.CanMaximize)
            info.extra_properties["CanMinimize"] = str(wp.CanMinimize)
            info.extra_properties["IsModal"] = str(wp.IsModal)
            info.extra_properties["IsTopmost"] = str(wp.IsTopmost)
    except Exception:
        pass

    return info


def _get_supported_patterns(ctrl: auto.Control) -> list[str]:
    """Check which UIA patterns the control supports."""
    supported = []
    for pattern_name in _PATTERN_NAMES:
        getter = f"Get{pattern_name}"
        try:
            method = getattr(ctrl, getter, None)
            if method:
                result = method()
                if result is not None:
                    supported.append(pattern_name)
        except Exception:
            continue
    return supported


def inspect_at_point(x: int, y: int, path: str = "") -> Optional[ElementInfo]:
    """Inspect the element at the given screen coordinates."""
    try:
        ctrl = auto.ControlFromPoint(x, y)
        if ctrl:
            return inspect_element(ctrl, path)
    except Exception:
        pass
    return None


def compare_elements(info_a: ElementInfo, info_b: ElementInfo) -> dict:
    """
    Compare two ElementInfo objects and return differences.
    Useful for debugging why locators fail.
    """
    dict_a = info_a.to_dict()
    dict_b = info_b.to_dict()

    all_keys = sorted(set(dict_a.keys()) | set(dict_b.keys()))
    diffs = {}
    for key in all_keys:
        val_a = dict_a.get(key, "(missing)")
        val_b = dict_b.get(key, "(missing)")
        if str(val_a) != str(val_b):
            diffs[key] = {"old": val_a, "new": val_b}
    return diffs
