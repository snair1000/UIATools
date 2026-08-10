"""
tree_walker.py - Walks the UIA tree and builds element paths.

The path format matches RPA.Windows convention:
    path:1|12|1|2|1
where each number is the 1-based child index at that depth level.

The Desktop root is implicitly index 1, so a top-level window that is
the 3rd child of Desktop would start with path:1|3.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

import uiautomation as auto

from src.core.uia_wrapper import (
    ElementInfo,
    control_to_element_info,
    get_children,
    get_root_element,
)

# Chromium/WebView2 builds its UIA accessibility tree LAZILY - only after a
# UIA client first touches it (WM_GETOBJECT). If a tree walk happens before
# that, the web content is invisible: the walk stops at the
# 'Chrome Legacy Window' / Chrome_RenderWidgetHostHWND host pane with no
# children. These helpers force activation before walking.

_WM_GETOBJECT = 0x003D
_OBJID_CLIENT = 0xFFFFFFFC  # -4 as DWORD
_WEBVIEW_HOST_CLASSES = ("Chrome_RenderWidgetHostHWND", "Chrome_WidgetWin")


def _activate_webview_accessibility(hwnd: int, settle_s: float = 0.3):
    """
    Send WM_GETOBJECT(OBJID_CLIENT) to every Chromium render-widget child
    window of hwnd so the browser builds its UIA tree for web content.
    No-op for windows without embedded Chromium/WebView2.
    """
    user32 = ctypes.windll.user32
    targets: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _enum_proc(child_hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child_hwnd, buf, 256)
        if any(buf.value.startswith(c) for c in _WEBVIEW_HOST_CLASSES):
            targets.append(child_hwnd)
        return True

    try:
        user32.EnumChildWindows(hwnd, _enum_proc, 0)
        for t in targets:
            result = ctypes.wintypes.DWORD()
            user32.SendMessageTimeoutW(
                t, _WM_GETOBJECT, 0, _OBJID_CLIENT,
                0x0002,  # SMTO_ABORTIFHUNG
                1000, ctypes.byref(result),
            )
        if targets:
            time.sleep(settle_s)  # give the renderer time to build the tree
    except Exception:
        pass


def _is_webview_host_node(info: ElementInfo) -> bool:
    cls = info.class_name or ""
    return (
        cls == "Chrome_RenderWidgetHostHWND"
        or cls.startswith("Chrome_WidgetWin")
        or "WebView2" in cls
        or info.name == "Chrome Legacy Window"
    )


@dataclass
class TreeNode:
    """A node in the cached UIA tree."""

    element_info: ElementInfo
    control: auto.Control
    children: list["TreeNode"] = field(default_factory=list)
    parent: Optional["TreeNode"] = None
    child_index: int = 1  # 1-based index among siblings
    depth: int = 0

    @property
    def path(self) -> str:
        """Return the RPA.Windows-style path string."""
        return self.element_info.path

    @property
    def display_name(self) -> str:
        """Friendly label for tree view."""
        info = self.element_info
        parts = []
        if info.control_type_name:
            parts.append(info.control_type_name)
        if info.name:
            label = info.name[:50] + ("..." if len(info.name) > 50 else "")
            parts.append(f'"{label}"')
        if info.automation_id:
            parts.append(f"[{info.automation_id}]")
        return " ".join(parts) or f"(child {self.child_index})"


def build_path(indices: list[int]) -> str:
    """Build a path string from a list of 1-based indices."""
    return "path:" + "|".join(str(i) for i in indices)


def walk_tree(
    root_control: auto.Control,
    max_depth: int = 8,
    root_indices: Optional[list[int]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> TreeNode:
    """
    Recursively walk the UIA tree starting from root_control.

    Args:
        root_control: Starting UIA control.
        max_depth: Maximum depth to traverse (prevents infinite recursion).
        root_indices: The path-index list for the root_control itself.
                      If None, defaults to [1] (Desktop root).
        progress_callback: Optional callable(status_text) for progress updates.

    Returns:
        The root TreeNode with children populated.
    """
    if root_indices is None:
        root_indices = [1]

    path_str = build_path(root_indices)
    root_info = control_to_element_info(root_control, path_str)
    root_node = TreeNode(
        element_info=root_info,
        control=root_control,
        depth=0,
        child_index=root_indices[-1] if root_indices else 1,
    )

    _walk_recursive(root_node, root_indices, 1, max_depth, progress_callback)
    return root_node


def _walk_recursive(
    parent_node: TreeNode,
    parent_indices: list[int],
    current_depth: int,
    max_depth: int,
    progress_callback: Optional[Callable[[str], None]] = None,
):
    """Recursively populate children."""
    if current_depth > max_depth:
        return

    children = get_children(parent_node.control)

    # WebView2/Chromium host with no children yet: the accessibility tree
    # may still be building - poke it and retry briefly.
    if not children and _is_webview_host_node(parent_node.element_info):
        hwnd = parent_node.element_info.native_window_handle
        for attempt in range(3):
            if hwnd:
                _activate_webview_accessibility(hwnd, settle_s=0.3 * (attempt + 1))
            else:
                time.sleep(0.3 * (attempt + 1))
            children = get_children(parent_node.control)
            if children:
                break

    for i, child_ctrl in enumerate(children, start=1):
        child_indices = parent_indices + [i]
        child_path = build_path(child_indices)
        child_info = control_to_element_info(child_ctrl, child_path)

        child_node = TreeNode(
            element_info=child_info,
            control=child_ctrl,
            parent=parent_node,
            child_index=i,
            depth=current_depth,
        )
        parent_node.children.append(child_node)

        if progress_callback and i % 5 == 0:
            progress_callback(f"Depth {current_depth}: scanned {i}/{len(children)} children at {child_path}")

        _walk_recursive(child_node, child_indices, current_depth + 1, max_depth, progress_callback)


def walk_from_window(
    window_control: auto.Control,
    max_depth: int = 8,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> TreeNode:
    """
    Walk the tree starting from a specific window.
    Determines the window's 1-based index among Desktop children first.
    """
    # Wake up any embedded Chromium/WebView2 content BEFORE walking, so web
    # elements (buttons, checkboxes...) are present in the captured tree.
    try:
        hwnd = window_control.NativeWindowHandle
        if hwnd:
            _activate_webview_accessibility(hwnd)
    except Exception:
        pass

    root = get_root_element()
    desktop_children = get_children(root)
    window_index = 1
    for i, child in enumerate(desktop_children, start=1):
        try:
            if child.NativeWindowHandle == window_control.NativeWindowHandle:
                window_index = i
                break
        except Exception:
            continue

    return walk_tree(
        window_control,
        max_depth=max_depth,
        root_indices=[1, window_index],
        progress_callback=progress_callback,
    )


def find_node_by_path(root_node: TreeNode, path: str) -> Optional[TreeNode]:
    """
    Find a tree node by its path string.
    e.g. path:1|3|2|1
    """
    if root_node.path == path:
        return root_node

    for child in root_node.children:
        result = find_node_by_path(child, path)
        if result:
            return result
    return None


def find_node_at_point(root_node: TreeNode, x: int, y: int) -> Optional[TreeNode]:
    """
    Find the deepest tree node whose bounding rectangle contains (x, y).
    """
    best: Optional[TreeNode] = None
    best_area = float("inf")

    def _check(node: TreeNode):
        nonlocal best, best_area
        rect = node.element_info.bounding_rect
        left, top, right, bottom = rect
        if left <= x <= right and top <= y <= bottom:
            area = (right - left) * (bottom - top)
            if area < best_area:
                best_area = area
                best = node
        for child in node.children:
            _check(child)

    _check(root_node)
    return best


def flatten_tree(root_node: TreeNode) -> list[TreeNode]:
    """Flatten the tree into a depth-first list."""
    result = [root_node]
    for child in root_node.children:
        result.extend(flatten_tree(child))
    return result
