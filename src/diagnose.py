"""
diagnose.py - Diagnostic script to test core UIA functionality.

Run with: python -m src.diagnose
This tests each layer independently to identify where failures occur.
"""

import sys
import ctypes
import ctypes.wintypes
import traceback


def test_com_init():
    """Test 1: COM initialization."""
    print("[1] Testing COM initialization...")
    import comtypes
    comtypes.CoInitialize()
    print("    COM initialized OK")


def test_uia_root():
    """Test 2: Can we get the Desktop root element?"""
    print("[2] Testing UIA root element...")
    import uiautomation as auto
    root = auto.GetRootControl()
    print(f"    Root Name: '{root.Name}'")
    print(f"    Root Handle: {root.NativeWindowHandle}")
    print(f"    Root Type: {root.ControlTypeName}")


def test_element_from_point():
    """Test 3: Can we find an element at the cursor position?"""
    print("[3] Testing ControlFromPoint at cursor position...")
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    print(f"    Cursor at: ({point.x}, {point.y})")

    import uiautomation as auto
    ctrl = auto.ControlFromPoint(point.x, point.y)
    print(f"    Element Name: '{ctrl.Name}'")
    print(f"    Element Type: {ctrl.ControlTypeName}")
    print(f"    Element Class: '{ctrl.ClassName}'")
    rect = ctrl.BoundingRectangle
    print(f"    BoundingRect: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")


def test_enumerate_windows():
    """Test 4: Can we enumerate top-level windows?"""
    print("[4] Testing window enumeration...")
    from src.utils.win_helpers import enumerate_top_level_windows
    windows = enumerate_top_level_windows()
    print(f"    Found {len(windows)} visible windows")
    for w in windows[:5]:
        print(f"    [{w['hwnd']:#010x}] {w['title'][:60]}")
    if len(windows) > 5:
        print(f"    ... and {len(windows) - 5} more")
    return windows


def test_control_from_handle(windows):
    """Test 5: Can we get a UIA control from a window handle?"""
    print("[5] Testing ControlFromHandle...")
    import uiautomation as auto
    if not windows:
        print("    SKIP: No windows available")
        return

    w = windows[0]
    hwnd = w["hwnd"]
    print(f"    Trying handle: {hwnd:#010x} ('{w['title'][:40]}')")

    # Method A: auto.ControlFromHandle
    try:
        ctrl = auto.ControlFromHandle(hwnd)
        print(f"    Method A (ControlFromHandle): Name='{ctrl.Name}', Type={ctrl.ControlTypeName}")
    except Exception as e:
        print(f"    Method A FAILED: {e}")

    # Method B: Direct COM ElementFromHandle
    try:
        iuia = auto._AutomationClient.instance().IUIAutomation
        element = iuia.ElementFromHandle(hwnd)
        if element:
            name = element.CurrentName
            print(f"    Method B (COM ElementFromHandle): Name='{name}'")
        else:
            print(f"    Method B: returned None")
    except Exception as e:
        print(f"    Method B FAILED: {e}")

    # Method C: Search Desktop children
    try:
        root = auto.GetRootControl()
        children = root.GetChildren()
        found = False
        for child in children:
            try:
                if child.NativeWindowHandle == hwnd:
                    print(f"    Method C (Desktop child search): Name='{child.Name}'")
                    found = True
                    break
            except Exception:
                continue
        if not found:
            print(f"    Method C: Handle not found among {len(children)} Desktop children")
    except Exception as e:
        print(f"    Method C FAILED: {e}")


def test_compare_elements():
    """Test 6: Can we compare two UIA elements?"""
    print("[6] Testing element comparison...")
    import uiautomation as auto

    root1 = auto.GetRootControl()
    root2 = auto.GetRootControl()

    # Method A: CompareElements
    try:
        iuia = auto._AutomationClient.instance().IUIAutomation
        result = iuia.CompareElements(root1.Element, root2.Element)
        print(f"    CompareElements(root, root) = {result} (expect True)")
    except Exception as e:
        print(f"    CompareElements FAILED: {e}")

    # Method B: NativeWindowHandle
    try:
        h1 = root1.NativeWindowHandle
        h2 = root2.NativeWindowHandle
        print(f"    Handle comparison: {h1} == {h2} -> {h1 == h2 and h1 != 0}")
    except Exception as e:
        print(f"    Handle comparison FAILED: {e}")


def test_parent_walk():
    """Test 7: Can we walk up the parent chain from an element?"""
    print("[7] Testing parent walk from cursor element...")
    import uiautomation as auto

    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))

    ctrl = auto.ControlFromPoint(point.x, point.y)
    print(f"    Starting from: '{ctrl.Name}' ({ctrl.ControlTypeName})")

    current = ctrl
    depth = 0
    while current and depth < 20:
        try:
            parent = current.GetParentControl()
        except Exception as e:
            print(f"    Depth {depth}: GetParentControl FAILED: {e}")
            break

        if parent is None:
            print(f"    Depth {depth}: parent is None (reached top)")
            break

        pname = "(error)"
        try:
            pname = parent.Name or "(empty)"
        except Exception:
            pass

        print(f"    Depth {depth}: '{current.Name or '(empty)'}' -> parent: '{pname}'")

        # Check if parent is same as current (root loops to itself)
        try:
            iuia = auto._AutomationClient.instance().IUIAutomation
            same = iuia.CompareElements(current.Element, parent.Element)
            if same:
                print(f"    Depth {depth}: parent == current (root element reached)")
                break
        except Exception:
            pass

        current = parent
        depth += 1


def test_coord_mapper():
    """Test 8: Full coord_mapper pipeline."""
    print("[8] Testing coord_mapper.map_point_to_element...")
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))

    from src.core.coord_mapper import map_point_to_element
    result = map_point_to_element(point.x, point.y)
    if result:
        print(f"    Path: {result.path}")
        print(f"    Name: '{result.element_info.name}'")
        print(f"    Type: {result.element_info.control_type_name}")
        print(f"    Rect: {result.element_info.bounding_rect}")
        print(f"    Center: ({result.element_info.center_x}, {result.element_info.center_y})")
        print(f"    Ancestors: {len(result.ancestors)}")
        for a_path, a_name in result.ancestors:
            print(f"      {a_path} -> '{a_name[:40]}'")
    else:
        print("    FAILED: map_point_to_element returned None")


def test_mouse_hook():
    """Test 9: Mouse hook installation (quick test)."""
    print("[9] Testing mouse hook installation...")
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Check GetModuleHandleW
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
    hmod = kernel32.GetModuleHandleW(None)
    print(f"    Module handle: {hmod:#018x}")
    print(f"    Handle fits 32-bit: {hmod < 2**32}")

    # Check if SetWindowsHookExW would need 64-bit handle
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    print(f"    Python pointer size: {ctypes.sizeof(ctypes.c_void_p)} bytes")
    print(f"    64-bit Python: {ctypes.sizeof(ctypes.c_void_p) == 8}")


def main():
    print("=" * 60)
    print("UIATools Diagnostic Report")
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Pointer size: {ctypes.sizeof(ctypes.c_void_p) * 8}-bit")
    print("=" * 60)
    print()
    print("Move your mouse cursor over a target app element,")
    print("then the tests will inspect whatever is under the cursor.")
    print()
    input("Press Enter to start diagnostics...")
    print()

    windows = []
    tests = [
        (test_com_init, None),
        (test_uia_root, None),
        (test_element_from_point, None),
        (test_enumerate_windows, "windows"),
        (test_control_from_handle, "needs_windows"),
        (test_compare_elements, None),
        (test_parent_walk, None),
        (test_coord_mapper, None),
        (test_mouse_hook, None),
    ]

    results = {}
    for test_func, flag in tests:
        try:
            if flag == "needs_windows":
                test_func(windows)
            elif flag == "windows":
                windows = test_func() or []
            else:
                test_func()
            results[test_func.__name__] = "PASSED"
            print(f"    ✓ PASSED\n")
        except Exception as e:
            results[test_func.__name__] = f"FAILED: {e}"
            print(f"    ✗ FAILED: {e}")
            traceback.print_exc()
            print()

    print("=" * 60)
    print("Summary:")
    for name, result in results.items():
        status = "✓" if result == "PASSED" else "✗"
        print(f"  {status} {name}: {result}")
    print("=" * 60)


if __name__ == "__main__":
    main()
