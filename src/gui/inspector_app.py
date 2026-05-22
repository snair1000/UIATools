"""
inspector_app.py - Main tkinter application for the UIATools Inspector.

Integrates all panels and provides:
- Window picker (select target application)
- Click-to-inspect mode (Ctrl+click to identify elements)
- Tree view of the UIA element hierarchy
- Property panel with locator export
- Path resolution and verification
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

import uiautomation as auto

from src.core.uia_wrapper import get_root_element, get_children, find_window_by_handle
from src.core.tree_walker import TreeNode, walk_tree, walk_from_window, find_node_at_point
from src.core.coord_mapper import map_point_to_element, resolve_path_to_element, CoordMapResult
from src.core.element_inspector import inspect_element
from src.core.recorder import Recorder, ActionType, RecordedStep
from src.gui.tree_panel import TreePanel
from src.gui.property_panel import PropertyPanel
from src.gui.recorder_panel import RecorderPanel
from src.gui.highlight import HighlightOverlay
from src.export.rf_exporter import export_element_locators, export_element_to_rf_keyword, export_elements_to_csv
from src.export.locator_strategy import build_locator_strategies
from src.utils.mouse_hook import MouseHook
from src.utils.win_helpers import enumerate_top_level_windows, get_cursor_pos


class InspectorApp:
    """Main application class for the UIA Element Inspector."""

    def __init__(self):
        self._root = tk.Tk()
        self._root.title("UIATools - Element Inspector for RPA.Windows")
        self._root.geometry("1280x800")
        self._root.minsize(800, 600)

        # State
        self._tree_root: Optional[TreeNode] = None
        self._inspect_mode = False
        self._record_mode = False
        self._mouse_hook: Optional[MouseHook] = None
        self._highlight = HighlightOverlay(color="red", border_width=3)
        self._target_window: Optional[auto.Control] = None
        self._recorder = Recorder()
        self._compact_mode = False

        self._setup_styles()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_panels()
        self._setup_statusbar()

        # Keyboard shortcuts
        self._root.bind("<F5>", lambda e: self._refresh_tree())
        self._root.bind("<Escape>", lambda e: self._stop_all_modes())
        self._root.bind("<Control-i>", lambda e: self._toggle_inspect())
        self._root.bind("<Control-r>", lambda e: self._toggle_record())
        self._root.bind("<Control-l>", lambda e: self._lookup_path())
        self._root.bind("<Control-m>", lambda e: self._toggle_compact_mode())
        self._root.bind("<Control-p>", lambda e: self._run_recorded_steps())
        self._root.bind("<F9>", lambda e: self._run_single_step())

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self):
        """Start the tkinter main loop."""
        self._set_status("Ready. Select a window or press Ctrl+I to start inspecting.")
        self._root.mainloop()

    # ── UI Setup ─────────────────────────────────────────────

    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()
        style.theme_use("clam")

    def _setup_menu(self):
        """Create the menu bar."""
        menubar = tk.Menu(self._root)
        self._root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Select Window...", command=self._show_window_picker)
        file_menu.add_command(label="Refresh Tree (F5)", command=self._refresh_tree)
        file_menu.add_separator()
        file_menu.add_command(label="Export All to File...", command=self._export_all_to_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # Inspect menu
        inspect_menu = tk.Menu(menubar, tearoff=0)
        inspect_menu.add_command(
            label="Toggle Click-to-Inspect (Ctrl+I)", command=self._toggle_inspect
        )
        inspect_menu.add_command(label="Inspect at Cursor", command=self._inspect_at_cursor)
        inspect_menu.add_command(label="Lookup Path... (Ctrl+L)", command=self._lookup_path)
        menubar.add_cascade(label="Inspect", menu=inspect_menu)

        # Record menu
        record_menu = tk.Menu(menubar, tearoff=0)
        record_menu.add_command(
            label="Toggle Recording (Ctrl+R)", command=self._toggle_record
        )
        record_menu.add_separator()
        record_menu.add_command(
            label="Run Recorded Steps (Ctrl+P)", command=self._run_recorded_steps
        )
        record_menu.add_command(
            label="Run Single Step (F9)", command=self._run_single_step
        )
        record_menu.add_command(
            label="Stop Playback", command=self._stop_playback
        )
        record_menu.add_separator()
        record_menu.add_command(
            label="Generate .robot File...", command=self._recorder_generate
        )
        record_menu.add_command(
            label="Save .robot File...", command=self._recorder_save
        )
        record_menu.add_command(
            label="Copy Keyword to Clipboard", command=self._recorder_copy_kw
        )
        record_menu.add_separator()
        record_menu.add_command(
            label="Clear Recorded Steps", command=self._recorder_clear
        )
        menubar.add_cascade(label="Record", menu=record_menu)

        # Export menu
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(
            label="Copy RF Locator (Path)", command=lambda: self._copy_rf_locator("path")
        )
        export_menu.add_command(
            label="Copy RF Locator (Best)", command=lambda: self._copy_rf_locator("best")
        )
        export_menu.add_command(
            label="Copy RF Keyword", command=self._copy_rf_keyword
        )
        export_menu.add_command(
            label="Export Locator Strategies", command=self._show_strategies
        )
        menubar.add_cascade(label="Export", menu=export_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Toggle Compact Mode (Ctrl+M)", command=self._toggle_compact_mode
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _setup_toolbar(self):
        """Create the toolbar."""
        toolbar = ttk.Frame(self._root, relief=tk.RAISED)
        toolbar.pack(fill=tk.X, padx=2, pady=2)

        ttk.Button(toolbar, text="📋 Select Window", command=self._show_window_picker).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🔄 Refresh (F5)", command=self._refresh_tree).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._inspect_btn = ttk.Button(
            toolbar, text="🎯 Click-to-Inspect (Ctrl+I)", command=self._toggle_inspect
        )
        self._inspect_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._record_btn = ttk.Button(
            toolbar, text="⏺ Record (Ctrl+R)", command=self._toggle_record
        )
        self._record_btn.pack(side=tk.LEFT, padx=2)

        self._run_btn = ttk.Button(
            toolbar, text="▶ Run (Ctrl+P)", command=self._run_recorded_steps
        )
        self._run_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._compact_btn = ttk.Button(
            toolbar, text="📐 Compact (Ctrl+M)", command=self._toggle_compact_mode
        )
        self._compact_btn.pack(side=tk.LEFT, padx=2)

        # Extra toolbar items (hidden in compact mode)
        self._toolbar_extra = ttk.Frame(toolbar)
        self._toolbar_extra.pack(side=tk.LEFT, fill=tk.X)

        ttk.Separator(self._toolbar_extra, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4
        )
        ttk.Button(
            self._toolbar_extra, text="📍 Inspect at Cursor", command=self._inspect_at_cursor
        ).pack(side=tk.LEFT, padx=2)

        # Path lookup
        ttk.Label(self._toolbar_extra, text="Path:").pack(side=tk.LEFT, padx=2)
        self._path_entry = ttk.Entry(self._toolbar_extra, width=30)
        self._path_entry.pack(side=tk.LEFT, padx=2)
        self._path_entry.bind("<Return>", lambda e: self._resolve_path_entry())
        ttk.Button(self._toolbar_extra, text="Go", command=self._resolve_path_entry).pack(
            side=tk.LEFT, padx=2
        )

        # Depth control
        ttk.Separator(self._toolbar_extra, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4
        )
        ttk.Label(self._toolbar_extra, text="Max Depth:").pack(side=tk.LEFT, padx=2)
        self._depth_var = tk.IntVar(value=8)
        depth_spin = ttk.Spinbox(
            self._toolbar_extra, from_=1, to=20, textvariable=self._depth_var, width=4
        )
        depth_spin.pack(side=tk.LEFT, padx=2)

    def _setup_panels(self):
        """Create the main panel layout."""
        # Main paned window: tree on left, tabbed panel on right
        self._paned = ttk.PanedWindow(self._root, orient=tk.HORIZONTAL)
        self._paned.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Tree panel (left)
        self._tree_panel = TreePanel(self._paned, on_select=self._on_tree_node_selected)
        self._paned.add(self._tree_panel, weight=1)

        # Right side: Notebook with Inspector tab and Recorder tab
        right_notebook = ttk.Notebook(self._paned)
        self._paned.add(right_notebook, weight=1)

        # ─── Inspector Tab ───
        inspector_tab = ttk.Frame(right_notebook)
        right_notebook.add(inspector_tab, text="🔍 Inspector")

        # Property panel
        self._prop_panel = PropertyPanel(inspector_tab)
        self._prop_panel.pack(fill=tk.BOTH, expand=True)

        # Export panel at bottom of inspector tab
        self._export_frame = ttk.LabelFrame(inspector_tab, text="Robot Framework Export")
        self._export_frame.pack(fill=tk.X, padx=2, pady=2)

        self._export_text = tk.Text(
            self._export_frame, height=6, font=("Consolas", 9), wrap=tk.WORD
        )
        self._export_text.pack(fill=tk.X, padx=4, pady=4)

        btn_row = ttk.Frame(self._export_frame)
        btn_row.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(btn_row, text="Copy RF Locator (Path)", command=lambda: self._copy_rf_locator("path")).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_row, text="Copy RF Locator (Best)", command=lambda: self._copy_rf_locator("best")).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_row, text="Copy RF Keyword", command=self._copy_rf_keyword).pack(
            side=tk.LEFT, padx=2
        )

        # ─── Recorder Tab ───
        recorder_tab = ttk.Frame(right_notebook)
        right_notebook.add(recorder_tab, text="⏺ Recorder")

        self._recorder_panel = RecorderPanel(
            recorder_tab,
            recorder=self._recorder,
            on_highlight_step=self._on_highlight_recorded_step,
        )
        self._recorder_panel.pack(fill=tk.BOTH, expand=True)

        self._right_notebook = right_notebook

    def _setup_statusbar(self):
        """Create the status bar."""
        self._status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self._root,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ── Actions ──────────────────────────────────────────────

    def _show_window_picker(self):
        """Show a dialog to select a target window."""
        picker = tk.Toplevel(self._root)
        picker.title("Select Target Window")
        picker.geometry("600x400")
        picker.transient(self._root)
        picker.grab_set()

        ttk.Label(picker, text="Select a window to inspect:", font=("Segoe UI", 10)).pack(
            padx=8, pady=4, anchor=tk.W
        )

        # Listbox of windows
        frame = ttk.Frame(picker)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        lb = tk.Listbox(frame, font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=lb.yview)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        windows = enumerate_top_level_windows()
        for w in windows:
            title = w["title"][:80]
            lb.insert(tk.END, f"[{w['hwnd']:08X}] {title} ({w['class_name']})")

        def on_select():
            sel = lb.curselection()
            if sel:
                w = windows[sel[0]]
                picker.destroy()
                self._load_window_by_handle(w["hwnd"])

        btn_frame = ttk.Frame(picker)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_frame, text="Select", command=on_select).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Refresh", command=lambda: self._refresh_window_list(lb, windows)).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=picker.destroy).pack(side=tk.RIGHT, padx=4)

        lb.bind("<Double-1>", lambda e: on_select())

    def _refresh_window_list(self, lb, windows_list):
        """Refresh the window list in the picker."""
        lb.delete(0, tk.END)
        windows_list.clear()
        windows_list.extend(enumerate_top_level_windows())
        for w in windows_list:
            title = w["title"][:80]
            lb.insert(tk.END, f"[{w['hwnd']:08X}] {title} ({w['class_name']})")

    def _load_window_by_handle(self, hwnd: int):
        """Load the tree for a window identified by its handle."""
        self._set_status(f"Loading tree for window 0x{hwnd:08X}...")

        def _do_load():
            import sys
            # Initialize COM on this background thread
            try:
                import ctypes as _ctypes
                _ctypes.windll.ole32.CoInitialize(0)
            except Exception:
                pass

            try:
                ctrl = find_window_by_handle(hwnd)
                if ctrl is None:
                    # Fallback: search Desktop children by handle
                    from src.core.uia_wrapper import get_root_element, get_children
                    root = get_root_element()
                    for child in get_children(root):
                        try:
                            if child.NativeWindowHandle == hwnd:
                                ctrl = child
                                break
                        except Exception:
                            continue

                if ctrl is None:
                    self._root.after(0, lambda: messagebox.showerror("Error", f"Window not found (handle={hwnd:#010x})."))
                    return

                self._target_window = ctrl
                tree = walk_from_window(
                    ctrl,
                    max_depth=self._depth_var.get(),
                    progress_callback=lambda s: self._root.after(0, self._set_status, s),
                )
                self._tree_root = tree

                def _update_ui():
                    self._tree_panel.load_tree(tree)
                    # Set target window for playback
                    self._recorder_panel.set_target_window(ctrl)
                    self._set_status(f"Tree loaded for: {ctrl.Name or '(unnamed)'}")

                self._root.after(0, _update_ui)
            except Exception as e:
                err_msg = f"Failed to load tree: {e}"
                print(f"[UIATools] {err_msg}", file=sys.stderr)
                import traceback; traceback.print_exc(file=sys.stderr)
                self._root.after(0, lambda: messagebox.showerror("Error", err_msg))

        threading.Thread(target=_do_load, daemon=True).start()

    def _refresh_tree(self):
        """Reload the tree for the current target window."""
        if self._target_window:
            try:
                hwnd = self._target_window.NativeWindowHandle
                self._load_window_by_handle(hwnd)
            except Exception:
                self._set_status("No target window. Use 'Select Window' first.")
        else:
            self._set_status("No target window. Use 'Select Window' first.")

    def _toggle_inspect(self):
        """Toggle click-to-inspect mode."""
        if self._inspect_mode:
            self._stop_inspect()
        else:
            self._start_inspect()

    def _start_inspect(self):
        """Enable click-to-inspect mode."""
        self._inspect_mode = True
        self._inspect_btn.config(text="🛑 Stop Inspecting (Ctrl+I)")
        self._set_status("INSPECT MODE: Hold Ctrl and click on any element to inspect it. Press Esc to stop.")
        self._start_mouse_hook()

    def _stop_inspect(self):
        """Disable click-to-inspect mode."""
        self._inspect_mode = False
        self._inspect_btn.config(text="🎯 Click-to-Inspect (Ctrl+I)")
        self._highlight.hide()
        if not self._record_mode:
            self._stop_mouse_hook()
        self._set_status("Inspect mode stopped.")

    # ── Record Mode ──────────────────────────────────────

    def _toggle_record(self):
        """Toggle recording mode."""
        if self._record_mode:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        """Enable recording mode."""
        self._record_mode = True
        self._record_btn.config(text="⏹ Stop Recording (Ctrl+R)")
        self._recorder_panel.start_recording_external()
        self._set_status("RECORDING: Hold Ctrl and click elements to record steps. Ctrl+R to stop.")
        # Switch to recorder tab
        self._right_notebook.select(1)
        self._start_mouse_hook()

    def _stop_record(self):
        """Disable recording mode."""
        self._record_mode = False
        self._record_btn.config(text="⏺ Record (Ctrl+R)")
        self._recorder_panel.stop_recording_external()
        if not self._inspect_mode:
            self._stop_mouse_hook()
        self._set_status(f"Recording stopped. {self._recorder.step_count} steps captured.")

    def _stop_all_modes(self):
        """Stop both inspect and record modes (Escape key)."""
        if self._inspect_mode:
            self._stop_inspect()
        if self._record_mode:
            self._stop_record()
        self._highlight.hide()

    # ── Compact / Full Mode ──────────────────────────────

    def _toggle_compact_mode(self):
        """Toggle between compact and full display modes."""
        if self._compact_mode:
            self._exit_compact_mode()
        else:
            self._enter_compact_mode()

    def _enter_compact_mode(self):
        """Switch to compact mode — locators + recorder only, smaller window."""
        self._compact_mode = True
        self._compact_btn.config(text="📐 Full Mode (Ctrl+M)")

        # Hide tree panel from paned window
        try:
            self._paned.forget(self._tree_panel)
        except Exception:
            pass

        # Hide extra toolbar items
        self._toolbar_extra.pack_forget()

        # Compact property panel (hide All Properties table)
        self._prop_panel.set_compact_mode(True)

        # Hide export frame
        self._export_frame.pack_forget()

        # Resize window for compact view
        self._root.geometry("620x520")
        self._root.minsize(400, 350)
        self._set_status("Compact mode. Press Ctrl+M to switch to full mode.")

    def _exit_compact_mode(self):
        """Switch back to full mode with all panels."""
        self._compact_mode = False
        self._compact_btn.config(text="📐 Compact (Ctrl+M)")

        # Restore tree panel in paned window (insert at position 0 = left)
        try:
            self._paned.insert(0, self._tree_panel, weight=1)
        except Exception:
            pass

        # Show extra toolbar items
        self._toolbar_extra.pack(side=tk.LEFT, fill=tk.X)

        # Full property panel (show All Properties table)
        self._prop_panel.set_compact_mode(False)

        # Restore export frame
        self._export_frame.pack(fill=tk.X, padx=2, pady=2)

        # Resize window for full view
        self._root.geometry("1280x800")
        self._root.minsize(800, 600)
        self._set_status("Full mode. Press Ctrl+M to switch to compact mode.")

    # ── Mouse Hook Management ────────────────────────────

    def _start_mouse_hook(self):
        """Start the global mouse hook if not already running."""
        if self._mouse_hook and self._mouse_hook.is_running:
            return  # already active

        def on_click(x, y, button):
            cx, cy = x, y
            self._root.after(0, lambda: self._on_hook_click(cx, cy, button))

        self._mouse_hook = MouseHook(on_click)
        self._mouse_hook.start()

    def _stop_mouse_hook(self):
        """Stop the global mouse hook."""
        if self._mouse_hook:
            self._mouse_hook.stop()
            self._mouse_hook = None

    def _on_hook_click(self, x: int, y: int, button: str):
        """Central handler for all mouse hook clicks (inspect and/or record)."""
        if button == "left":
            if self._record_mode:
                self._record_click_at(x, y, button)
            elif self._inspect_mode:
                self._inspect_at(x, y)
        elif button == "right":
            if self._record_mode:
                self._record_click_at(x, y, button)

    def _record_click_at(self, x: int, y: int, button: str):
        """Record a click and also show the element in the inspector."""
        self._set_status(f"Recording click at ({x}, {y})...")

        def _do_record():
            import sys
            try:
                import ctypes as _ctypes
                _ctypes.windll.ole32.CoInitialize(0)
            except Exception:
                pass

            try:
                result = map_point_to_element(x, y)
                if result is None:
                    self._root.after(0, lambda: self._set_status(f"No element at ({x}, {y})"))
                    return

                info = inspect_element(result.control, result.path)

                # Record the step
                step = self._recorder.add_click(x, y, info, button)

                def _update():
                    # Also show in inspector
                    self._prop_panel.show_element(info)
                    self._show_export_text(info)

                    rect = info.bounding_rect
                    if rect != (0, 0, 0, 0):
                        self._highlight.show(*rect)

                    if self._tree_root:
                        self._tree_panel.select_node_by_path(info.path)

                    step_num = step.step_number if step else "?"
                    self._set_status(
                        f"Recorded step {step_num}: {info.control_type_name} "
                        f"'{info.name}' at {info.path}"
                    )

                self._root.after(0, _update)
            except Exception as e:
                err_msg = f"Record error: {e}"
                print(f"[UIATools] {err_msg}", file=sys.stderr)
                import traceback; traceback.print_exc(file=sys.stderr)
                self._root.after(0, lambda: self._set_status(err_msg))

        threading.Thread(target=_do_record, daemon=True).start()

    def _on_highlight_recorded_step(self, step: RecordedStep):
        """Highlight element when a recorded step is selected in the panel."""
        info = step.element_info
        self._prop_panel.show_element(info)
        self._show_export_text(info)
        rect = info.bounding_rect
        if rect != (0, 0, 0, 0):
            self._highlight.show(*rect)
        else:
            self._highlight.hide()

    # ── Recorder menu delegates ──────────────────────────

    def _recorder_generate(self):
        self._right_notebook.select(1)
        self._recorder_panel._generate_code()

    def _recorder_save(self):
        self._right_notebook.select(1)
        self._recorder_panel._save_robot_file()

    def _recorder_copy_kw(self):
        self._recorder_panel._copy_keyword()

    def _recorder_clear(self):
        self._recorder_panel._clear_steps()

    def _run_recorded_steps(self):
        """Run all recorded steps."""
        self._right_notebook.select(1)
        self._recorder_panel._play_all()

    def _run_single_step(self):
        """Run a single step."""
        self._right_notebook.select(1)
        self._recorder_panel._play_step()

    def _stop_playback(self):
        """Stop playback."""
        self._recorder_panel._stop_execution()

    def _inspect_at_cursor(self):
        """Inspect the element at the current cursor position."""
        x, y = get_cursor_pos()
        self._inspect_at(x, y)

    def _inspect_at(self, x: int, y: int):
        """Inspect the element at the given screen coordinates."""
        self._set_status(f"Inspecting at ({x}, {y})...")

        def _do_inspect():
            import sys
            # Initialize COM on this background thread
            try:
                import ctypes as _ctypes
                _ctypes.windll.ole32.CoInitialize(0)
            except Exception:
                pass

            try:
                result = map_point_to_element(x, y)
                if result is None:
                    self._root.after(0, lambda: self._set_status(f"No element found at ({x}, {y})"))
                    return

                # Deep inspection
                info = inspect_element(result.control, result.path)

                def _update():
                    self._prop_panel.show_element(info)
                    self._show_export_text(info)

                    # Highlight the element
                    rect = info.bounding_rect
                    if rect != (0, 0, 0, 0):
                        self._highlight.show(*rect)

                    # Try to select in tree
                    if self._tree_root:
                        self._tree_panel.select_node_by_path(info.path)

                    self._set_status(
                        f"Found: {info.control_type_name} '{info.name}' at {info.path}"
                    )

                self._root.after(0, _update)
            except Exception as e:
                err_msg = f"Inspect error: {e}"
                print(f"[UIATools] {err_msg}", file=sys.stderr)
                import traceback; traceback.print_exc(file=sys.stderr)
                self._root.after(0, lambda: self._set_status(err_msg))

        threading.Thread(target=_do_inspect, daemon=True).start()

    def _on_tree_node_selected(self, node: TreeNode):
        """Handle tree node selection."""
        info = node.element_info

        # Deep inspect the selected control
        try:
            detailed = inspect_element(node.control, info.path)
            self._prop_panel.show_element(detailed)
            self._show_export_text(detailed)
        except Exception:
            self._prop_panel.show_element(info)
            self._show_export_text(info)

        # Highlight
        rect = info.bounding_rect
        if rect != (0, 0, 0, 0):
            self._highlight.show(*rect)
        else:
            self._highlight.hide()

        self._set_status(f"Selected: {info.control_type_name} '{info.name}' - {info.path}")

    def _lookup_path(self):
        """Show a dialog to enter a path and resolve it."""
        dialog = tk.Toplevel(self._root)
        dialog.title("Lookup Element by Path")
        dialog.geometry("400x120")
        dialog.transient(self._root)
        dialog.grab_set()

        ttk.Label(dialog, text="Enter RPA.Windows path (e.g., path:1|3|2|1):").pack(
            padx=8, pady=4, anchor=tk.W
        )
        entry = ttk.Entry(dialog, width=50)
        entry.pack(padx=8, pady=4, fill=tk.X)
        entry.focus()

        def on_go():
            path = entry.get().strip()
            dialog.destroy()
            self._resolve_path(path)

        entry.bind("<Return>", lambda e: on_go())
        ttk.Button(dialog, text="Resolve", command=on_go).pack(padx=8, pady=4)

    def _resolve_path_entry(self):
        """Resolve the path from the toolbar entry."""
        path = self._path_entry.get().strip()
        if path:
            if not path.startswith("path:"):
                path = "path:" + path
            self._resolve_path(path)

    def _resolve_path(self, path: str):
        """Resolve a path string and show the element."""
        if not path:
            return

        self._set_status(f"Resolving {path}...")

        def _do_resolve():
            import sys
            # Initialize COM on this background thread
            try:
                import ctypes as _ctypes
                _ctypes.windll.ole32.CoInitialize(0)
            except Exception:
                pass

            try:
                ctrl = resolve_path_to_element(path)
                if ctrl is None:
                    self._root.after(
                        0, lambda: messagebox.showwarning("Not Found", f"No element at: {path}")
                    )
                    return

                info = inspect_element(ctrl, path)

                def _update():
                    self._prop_panel.show_element(info)
                    self._show_export_text(info)
                    rect = info.bounding_rect
                    if rect != (0, 0, 0, 0):
                        self._highlight.show(*rect)
                    self._set_status(f"Resolved: {info.control_type_name} '{info.name}' at {path}")

                self._root.after(0, _update)
            except Exception as e:
                err_msg = f"Failed to resolve path: {e}"
                print(f"[UIATools] {err_msg}", file=sys.stderr)
                import traceback; traceback.print_exc(file=sys.stderr)
                self._root.after(
                    0, lambda: messagebox.showerror("Error", err_msg)
                )

        threading.Thread(target=_do_resolve, daemon=True).start()

    # ── Export ───────────────────────────────────────────────

    def _show_export_text(self, info):
        """Update the export text area with RF locator info."""
        from src.core.uia_wrapper import ElementInfo

        strategies = build_locator_strategies(info)
        lines = ["# Locator Strategies (best → fallback):"]
        for i, s in enumerate(strategies, 1):
            lines.append(f"# {i}. {s['type']}: {s['locator']}  (reliability: {s['reliability']})")

        lines.append("")
        lines.append(export_element_to_rf_keyword(info))

        self._export_text.delete("1.0", tk.END)
        self._export_text.insert("1.0", "\n".join(lines))

    def _copy_rf_locator(self, mode: str):
        """Copy an RF locator to clipboard."""
        node = self._tree_panel.get_selected_node()
        info = node.element_info if node else (self._prop_panel._current_info if self._prop_panel._current_info else None)
        if not info:
            self._set_status("No element selected.")
            return

        if mode == "path":
            locator = info.path
        else:
            strategies = build_locator_strategies(info)
            locator = strategies[0]["locator"] if strategies else info.path

        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(locator)
            self._set_status(f"Copied to clipboard: {locator}")
        except Exception:
            pass

    def _copy_rf_keyword(self):
        """Copy an RF keyword line to clipboard."""
        node = self._tree_panel.get_selected_node()
        info = node.element_info if node else (self._prop_panel._current_info if self._prop_panel._current_info else None)
        if not info:
            self._set_status("No element selected.")
            return

        kw = export_element_to_rf_keyword(info)
        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(kw)
            self._set_status("Copied RF keyword to clipboard.")
        except Exception:
            pass

    def _show_strategies(self):
        """Show a dialog with all locator strategies for the selected element."""
        node = self._tree_panel.get_selected_node()
        info = node.element_info if node else (self._prop_panel._current_info if self._prop_panel._current_info else None)
        if not info:
            messagebox.showinfo("No Element", "Select an element first.")
            return

        strategies = build_locator_strategies(info)
        dialog = tk.Toplevel(self._root)
        dialog.title("Locator Strategies")
        dialog.geometry("600x300")
        dialog.transient(self._root)

        text = tk.Text(dialog, font=("Consolas", 10), wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        for s in strategies:
            text.insert(tk.END, f"[{s['reliability']}] {s['type']}:\n")
            text.insert(tk.END, f"  {s['locator']}\n")
            text.insert(tk.END, f"  Notes: {s['notes']}\n\n")

        text.config(state=tk.DISABLED)

    def _export_all_to_file(self):
        """Export all elements in the tree to a file."""
        if not self._tree_root:
            messagebox.showinfo("No Tree", "Load a tree first.")
            return

        path = filedialog.asksaveasfilename(
            title="Export All Elements",
            defaultextension=".robot",
            filetypes=[
                ("Robot Framework", "*.robot"),
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            from src.core.tree_walker import flatten_tree

            nodes = flatten_tree(self._tree_root)

            # Use CSV format for .csv files
            if path.lower().endswith(".csv"):
                content = export_elements_to_csv(nodes)
            else:
                lines = export_element_locators(nodes)
                content = "\n".join(lines)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self._set_status(f"Exported {len(nodes)} elements to {path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # ── Helpers ──────────────────────────────────────────────

    def _set_status(self, text: str):
        """Update the status bar text."""
        self._status_var.set(text)

    def _show_about(self):
        """Show the about dialog."""
        messagebox.showinfo(
            "About UIATools",
            "UIATools - UI Automation Element Inspector\n\n"
            "Accelerates migration from WinAppDriver to\n"
            "Robot Framework's RPA.Windows library.\n\n"
            "Identifies UI elements by coordinates,\n"
            "bounding rectangles, and tree paths.\n\n"
            "Path format: path:1|12|1|2|1",
        )

    def _on_close(self):
        """Handle window close."""
        self._stop_all_modes()
        self._highlight.destroy()
        self._root.destroy()
