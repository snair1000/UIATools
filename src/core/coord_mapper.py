"""
coord_mapper.py - Maps screen (x, y) coordinates to UIA elements and paths.

This is the key bridge between:
  - clicking on screen → finding the element → getting its path
  - having a path → finding the element → getting its bounding rect / center

It combines the tree walker and element inspector to provide a complete
mapping between screen coordinates and RPA.Windows locator paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import uiautomation as auto

from src.core.uia_wrapper import (
    ElementInfo,
    control_to_element_info,
    element_from_point,
    get_children,
    get_root_element,
)
from src.core.tree_walker import TreeNode, build_path, walk_from_window


@dataclass
class CoordMapResult:
    """Result of mapping coordinates to an element."""

    element_info: ElementInfo
    path: str
    control: auto.Control
    ancestors: list[tuple[str, str]]  # list of (path, display_name) from root to element


def map_point_to_element(x: int, y: int, max_depth: int = 100) -> Optional[CoordMapResult]:
    """
    Given screen coordinates (x, y), find the deepest UIA element at that
    point and compute its full RPA.Windows path.

    This works by:
    1. Using ControlFromPoint to find the element at (x, y).
    2. Walking up the parent chain to the Desktop root.
    3. At each level, finding the 1-based child index.
    4. Reversing to get the full path from root to element.

    Args:
        x: Screen X coordinate.
        y: Screen Y coordinate.
        max_depth: Safety limit to prevent infinite loops.

    Returns:
        CoordMapResult with element info, path, and ancestry, or None.
    """
    ctrl = element_from_point(x, y)
    if ctrl is None:
        return None

    return map_control_to_path(ctrl, max_depth)


def map_control_to_path(ctrl: auto.Control, max_depth: int = 100) -> Optional[CoordMapResult]:
    """
    Given a UIA control, compute its full RPA.Windows path by walking
    up the parent chain.

    Args:
        ctrl: The UIA control to map.
        max_depth: Safety limit.

    Returns:
        CoordMapResult or None.
    """
    # Build the ancestor chain from element up to Desktop
    chain: list[tuple[auto.Control, int]] = []  # (control, child_index)
    current = ctrl
    depth = 0
    reached_root = False

    while current is not None and depth < max_depth:
        parent = _get_parent(current)
        if parent is None:
            # We've reached the root (Desktop)
            chain.append((current, 1))  # Desktop is always index 1
            reached_root = True
            break

        # Find current's 1-based index among parent's children
        child_index = _find_child_index(parent, current)
        chain.append((current, child_index))
        current = parent
        depth += 1

    # If we hit max_depth without reaching root, try one more parent check
    if not reached_root and current is not None:
        parent = _get_parent(current)
        if parent is None:
            chain.append((current, 1))  # Desktop root

    if not chain:
        return None

    # Reverse to get root-to-element order
    chain.reverse()

    # Build path indices and ancestor display info
    indices = [item[1] for item in chain]
    path_str = build_path(indices)

    ancestors = []
    for i, (ancestor_ctrl, idx) in enumerate(chain):
        ancestor_path = build_path(indices[: i + 1])
        try:
            name = ancestor_ctrl.Name or ancestor_ctrl.ControlTypeName or f"(child {idx})"
        except Exception:
            name = f"(child {idx})"
        ancestors.append((ancestor_path, name))

    # Build the final element info
    element_info = control_to_element_info(ctrl, path_str)

    return CoordMapResult(
        element_info=element_info,
        path=path_str,
        control=ctrl,
        ancestors=ancestors,
    )


def _get_parent(ctrl: auto.Control) -> Optional[auto.Control]:
    """Get the parent of a UIA control, returning None for the Desktop root."""
    try:
        # If ctrl itself IS the Desktop root, it has no parent
        root = get_root_element()
        if _same_control(ctrl, root):
            return None
        parent = ctrl.GetParentControl()
        if parent is None:
            return None
        # Guard: if parent is the same element (root loops to itself)
        if _same_control(parent, ctrl):
            return None
        return parent
    except Exception:
        return None


def _find_child_index(parent: auto.Control, target: auto.Control) -> int:
    """Find the 1-based index of target among parent's children."""
    children = get_children(parent)
    for i, child in enumerate(children, start=1):
        if _same_control(child, target):
            return i
    # Fallback: if we can't match by identity, try matching by bounding rect
    try:
        target_rect = target.BoundingRectangle
        for i, child in enumerate(children, start=1):
            try:
                child_rect = child.BoundingRectangle
                if (
                    child_rect.left == target_rect.left
                    and child_rect.top == target_rect.top
                    and child_rect.right == target_rect.right
                    and child_rect.bottom == target_rect.bottom
                ):
                    return i
            except Exception:
                continue
    except Exception:
        pass
    return 1  # fallback


def _same_control(a: auto.Control, b: auto.Control) -> bool:
    """Check if two controls refer to the same UIA element."""
    # Method 1: Compare by native window handle (fast, works for windowed controls)
    try:
        ha = a.NativeWindowHandle
        hb = b.NativeWindowHandle
        if ha and hb and ha != 0 and hb != 0:
            return ha == hb
    except Exception:
        pass

    # Method 2: Use IUIAutomation.CompareElements via the uiautomation library
    try:
        # Try different known internal API names across uiautomation versions
        iuia = None
        for attr in ('_AutomationClient', 'AutomationClient', '_iuia'):
            client_cls = getattr(auto, attr, None)
            if client_cls is not None:
                if callable(getattr(client_cls, 'instance', None)):
                    iuia = client_cls.instance().IUIAutomation
                break
        if iuia is not None:
            return bool(iuia.CompareElements(a.Element, b.Element))
    except Exception:
        pass

    # Method 3: Compare by combined properties (BoundingRect + ControlType + ClassName + Name)
    try:
        if a.ControlType != b.ControlType:
            return False
        if a.ClassName != b.ClassName:
            return False
        if a.Name != b.Name:
            return False
        ra = a.BoundingRectangle
        rb = b.BoundingRectangle
        if (
            ra.left == rb.left
            and ra.top == rb.top
            and ra.right == rb.right
            and ra.bottom == rb.bottom
        ):
            return True
    except Exception:
        pass

    return False


def resolve_path_to_element(path: str) -> Optional[auto.Control]:
    """
    Given a path string like "path:1|3|2|1", navigate from Desktop
    to find the target element.

    Returns the UIA Control at that path, or None if not found.
    """
    if not path.startswith("path:"):
        return None

    indices_str = path[5:]  # strip "path:"
    try:
        indices = [int(x) for x in indices_str.split("|")]
    except ValueError:
        return None

    if not indices or indices[0] != 1:
        return None

    current = get_root_element()

    for idx in indices[1:]:  # skip the first 1 (Desktop root)
        children = get_children(current)
        if idx < 1 or idx > len(children):
            return None
        current = children[idx - 1]  # convert 1-based to 0-based

    return current


def resolve_path_to_info(path: str) -> Optional[ElementInfo]:
    """Resolve a path string to a full ElementInfo."""
    ctrl = resolve_path_to_element(path)
    if ctrl:
        return control_to_element_info(ctrl, path)
    return None
