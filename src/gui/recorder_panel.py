"""
recorder_panel.py - GUI panel for recording and managing interaction steps.

Provides:
  - Start/Stop/Clear recording controls
  - Step list showing each recorded action with element info
  - Per-step editing: change action type, set text input, override locator
  - Reorder steps (move up/down), delete steps
  - Add manual steps (Type Text, Wait, etc.)
  - Generate code button → opens generated .robot file in a text window
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from typing import Callable, Optional

from src.core.recorder import ActionType, RecordedStep, Recorder
from src.core.step_executor import StepExecutor, ExecutionStatus, StepResult
from src.export.rf_code_generator import generate_robot_file, generate_keyword_only


class RecorderPanel(ttk.Frame):
    """
    Panel for recording and managing interaction steps.
    """

    def __init__(
        self,
        parent: tk.Widget,
        recorder: Recorder,
        on_highlight_step: Optional[Callable[[RecordedStep], None]] = None,
    ):
        super().__init__(parent)
        self._recorder = recorder
        self._on_highlight_step = on_highlight_step
        
        # Step executor for playback
        self._executor = StepExecutor()
        self._executor.set_on_step_start(self._on_execution_step_start)
        self._executor.set_on_step_complete(self._on_execution_step_complete)
        self._executor.set_on_execution_complete(self._on_execution_complete)
        self._executor.set_on_status_update(self._on_execution_status)
        
        self._setup_ui()

        # Wire up recorder callback
        self._recorder.set_on_step_added(self._on_step_added_callback)

    def set_target_window(self, window):
        """Set the target window for scoped element searches during playback."""
        self._executor.set_target_window(window)

    def _setup_ui(self):
        """Build the recorder panel UI."""
        # ─── Top controls ───
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        self._record_btn = ttk.Button(
            ctrl_frame, text="⏺ Start Recording", command=self._toggle_recording
        )
        self._record_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl_frame, text="🗑 Clear", command=self._clear_steps).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(ctrl_frame, text="📄 Generate .robot", command=self._generate_code).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ctrl_frame, text="💾 Save .robot", command=self._save_robot_file).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ctrl_frame, text="📋 Copy Keyword", command=self._copy_keyword).pack(
            side=tk.LEFT, padx=2
        )

        # Recording indicator
        self._status_var = tk.StringVar(value="Not recording")
        self._status_label = ttk.Label(
            ctrl_frame, textvariable=self._status_var, foreground="gray"
        )
        self._status_label.pack(side=tk.RIGHT, padx=8)

        # ─── Playback controls ───
        playback_frame = ttk.Frame(self)
        playback_frame.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(playback_frame, text="▶ Playback:", font=("Segoe UI", 9, "bold")).pack(
            side=tk.LEFT, padx=2
        )

        self._play_btn = ttk.Button(
            playback_frame, text="▶ Run All", width=10, command=self._play_all
        )
        self._play_btn.pack(side=tk.LEFT, padx=2)

        self._step_btn = ttk.Button(
            playback_frame, text="⏭ Step", width=8, command=self._play_step
        )
        self._step_btn.pack(side=tk.LEFT, padx=2)

        self._pause_btn = ttk.Button(
            playback_frame, text="⏸ Pause", width=8, command=self._pause_execution, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=2)

        self._stop_btn = ttk.Button(
            playback_frame, text="⏹ Stop", width=8, command=self._stop_execution, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(playback_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(playback_frame, text="Delay:").pack(side=tk.LEFT, padx=2)
        self._delay_var = tk.DoubleVar(value=0.5)
        delay_spin = ttk.Spinbox(
            playback_frame, from_=0.0, to=5.0, increment=0.1,
            textvariable=self._delay_var, width=5
        )
        delay_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(playback_frame, text="s").pack(side=tk.LEFT)

        ttk.Separator(playback_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # Wait settings
        self._auto_wait_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            playback_frame, text="Wait for ready", variable=self._auto_wait_var
        ).pack(side=tk.LEFT, padx=2)

        ttk.Label(playback_frame, text="Wait after:").pack(side=tk.LEFT, padx=2)
        self._wait_after_var = tk.DoubleVar(value=0.3)
        wait_spin = ttk.Spinbox(
            playback_frame, from_=0.0, to=5.0, increment=0.1,
            textvariable=self._wait_after_var, width=5
        )
        wait_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(playback_frame, text="s").pack(side=tk.LEFT)

        # Execution progress
        self._exec_status_var = tk.StringVar(value="")
        self._exec_status_label = ttk.Label(
            playback_frame, textvariable=self._exec_status_var, foreground="blue"
        )
        self._exec_status_label.pack(side=tk.RIGHT, padx=8)

        # ─── Step list ───
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        columns = ("action", "element", "locator", "text", "status")
        self._step_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=10,
        )
        self._step_tree.heading("#0", text="#", anchor=tk.W)
        self._step_tree.heading("action", text="Action", anchor=tk.W)
        self._step_tree.heading("element", text="Element", anchor=tk.W)
        self._step_tree.heading("locator", text="Locator", anchor=tk.W)
        self._step_tree.heading("text", text="Text Input", anchor=tk.W)
        self._step_tree.heading("status", text="Status", anchor=tk.W)

        self._step_tree.column("#0", width=40, minwidth=30)
        self._step_tree.column("action", width=90, minwidth=70)
        self._step_tree.column("element", width=150, minwidth=100)
        self._step_tree.column("locator", width=180, minwidth=100)
        self._step_tree.column("text", width=100, minwidth=60)
        self._step_tree.column("status", width=80, minwidth=60)

        # Configure tags for status colors
        self._step_tree.tag_configure("success", foreground="green")
        self._step_tree.tag_configure("failed", foreground="red")
        self._step_tree.tag_configure("running", foreground="blue")
        self._step_tree.tag_configure("skipped", foreground="gray")

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._step_tree.yview)
        self._step_tree.configure(yscrollcommand=vsb.set)
        self._step_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._step_tree.bind("<<TreeviewSelect>>", self._on_step_selected)
        self._step_tree.bind("<Double-1>", self._on_step_double_click)

        # ─── Step editing buttons ───
        edit_frame = ttk.Frame(self)
        edit_frame.pack(fill=tk.X, padx=4, pady=2)

        ttk.Button(edit_frame, text="⬆", width=3, command=self._move_up).pack(
            side=tk.LEFT, padx=1
        )
        ttk.Button(edit_frame, text="⬇", width=3, command=self._move_down).pack(
            side=tk.LEFT, padx=1
        )
        ttk.Button(edit_frame, text="❌ Delete", command=self._delete_step).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Separator(edit_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(
            edit_frame, text="✏ Change Action", command=self._change_action
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="📝 Set Text", command=self._set_text_input
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="🔗 Override Locator", command=self._override_locator
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="⏱ Set Wait", command=self._set_step_wait
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="➕ Add Type Text", command=self._add_type_text_step
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="➕ Add Wait", command=self._add_wait_step
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            edit_frame, text="⌨ Add Send Keys", command=self._add_send_keys_step
        ).pack(side=tk.LEFT, padx=2)

    # ── Recording controls ────────────────────────────────

    def _toggle_recording(self):
        """Start or stop recording."""
        if self._recorder.is_recording:
            self._recorder.stop()
            self._record_btn.config(text="⏺ Start Recording")
            self._status_var.set(f"Stopped ({self._recorder.step_count} steps)")
            self._status_label.config(foreground="gray")
        else:
            self._recorder.start()
            self._record_btn.config(text="⏹ Stop Recording")
            self._status_var.set("🔴 RECORDING...")
            self._status_label.config(foreground="red")

    def _clear_steps(self):
        """Clear all recorded steps."""
        if self._recorder.step_count > 0:
            if not messagebox.askyesno("Clear", "Delete all recorded steps?"):
                return
        self._recorder.clear()
        self._refresh_step_list()
        self._status_var.set("Cleared")

    def start_recording_external(self):
        """Called by inspector_app to start recording programmatically."""
        if not self._recorder.is_recording:
            self._toggle_recording()

    def stop_recording_external(self):
        """Called by inspector_app to stop recording programmatically."""
        if self._recorder.is_recording:
            self._toggle_recording()

    # ── Step list management ──────────────────────────────

    def _on_step_added_callback(self, step: RecordedStep):
        """Called by the Recorder when a new step is recorded."""
        self._add_step_to_tree(step)
        count = self._recorder.step_count
        self._status_var.set(f"🔴 RECORDING... ({count} steps)")

    def _add_step_to_tree(self, step: RecordedStep, status: str = ""):
        """Add a single step to the treeview."""
        info = step.element_info
        name = info.name[:25] if info.name else info.control_type_name
        if info.automation_id:
            name += f" [{info.automation_id[:15]}]"

        item_id = self._step_tree.insert(
            "",
            "end",
            text=str(step.step_number),
            values=(
                step.action.value,
                name,
                step.locator[:50],
                step.text_input[:30] if step.text_input else "",
                status,
            ),
        )
        self._step_tree.see(item_id)
        self._step_tree.selection_set(item_id)

    def _refresh_step_list(self):
        """Rebuild the entire step list from the recorder."""
        self._step_tree.delete(*self._step_tree.get_children())
        for step in self._recorder.steps:
            self._add_step_to_tree(step)

    def _get_selected_index(self) -> int:
        """Return the index of the selected step, or -1."""
        sel = self._step_tree.selection()
        if not sel:
            return -1
        items = self._step_tree.get_children()
        for i, item_id in enumerate(items):
            if item_id == sel[0]:
                return i
        return -1

    def _on_step_selected(self, event):
        """Handle step selection → highlight the element."""
        idx = self._get_selected_index()
        if idx >= 0 and self._on_highlight_step:
            steps = self._recorder.steps
            if idx < len(steps):
                self._on_highlight_step(steps[idx])

    def _on_step_double_click(self, event):
        """Double-click to change action type."""
        self._change_action()

    # ── Step editing ──────────────────────────────────────

    def _move_up(self):
        idx = self._get_selected_index()
        if idx > 0:
            self._recorder.move_step_up(idx)
            self._refresh_step_list()
            # Re-select the moved item
            items = self._step_tree.get_children()
            if idx - 1 < len(items):
                self._step_tree.selection_set(items[idx - 1])

    def _move_down(self):
        idx = self._get_selected_index()
        if idx >= 0:
            self._recorder.move_step_down(idx)
            self._refresh_step_list()
            items = self._step_tree.get_children()
            if idx + 1 < len(items):
                self._step_tree.selection_set(items[idx + 1])

    def _delete_step(self):
        idx = self._get_selected_index()
        if idx >= 0:
            self._recorder.remove_step(idx)
            self._refresh_step_list()

    def _change_action(self):
        """Show a dialog to change the action type of the selected step."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step first.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Change Action Type")
        dialog.geometry("300x280")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Select action type:").pack(padx=8, pady=4)

        action_var = tk.StringVar()
        current = self._recorder.steps[idx].action
        action_var.set(current.value)

        for action in ActionType:
            ttk.Radiobutton(
                dialog, text=action.value, variable=action_var, value=action.value
            ).pack(anchor=tk.W, padx=16)

        def apply():
            chosen = action_var.get()
            for action in ActionType:
                if action.value == chosen:
                    self._recorder.update_step_action(idx, action)
                    break
            dialog.destroy()
            self._refresh_step_list()

        ttk.Button(dialog, text="Apply", command=apply).pack(pady=8)

    def _set_text_input(self):
        """Set text input for the selected step (for Type Text, Set Value, etc.)."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step first.")
            return

        current = self._recorder.steps[idx].text_input
        text = simpledialog.askstring(
            "Text Input",
            "Enter the text to type/set:",
            initialvalue=current,
            parent=self,
        )
        if text is not None:
            self._recorder.update_step_text(idx, text)
            self._refresh_step_list()

    def _override_locator(self):
        """Override the auto-chosen locator for the selected step."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step first.")
            return

        step = self._recorder.steps[idx]
        current = step.locator_override or step.locator

        # Show dialog with all available strategies
        dialog = tk.Toplevel(self)
        dialog.title("Override Locator")
        dialog.geometry("550x350")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Available locator strategies:").pack(padx=8, pady=4)

        from src.export.locator_strategy import build_locator_strategies
        strategies = build_locator_strategies(step.element_info)

        lb = tk.Listbox(dialog, font=("Consolas", 9), height=8)
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        for s in strategies:
            lb.insert(tk.END, f"[{s['reliability']}] {s['locator']}")

        ttk.Label(dialog, text="Or enter custom locator:").pack(padx=8, pady=2)
        entry = ttk.Entry(dialog, font=("Consolas", 9))
        entry.insert(0, current)
        entry.pack(fill=tk.X, padx=8, pady=2)

        def on_select(event=None):
            sel = lb.curselection()
            if sel:
                locator = strategies[sel[0]]["locator"]
                entry.delete(0, tk.END)
                entry.insert(0, locator)

        lb.bind("<<ListboxSelect>>", on_select)

        def apply():
            locator = entry.get().strip()
            if locator:
                self._recorder.update_step_locator(idx, locator)
            dialog.destroy()
            self._refresh_step_list()

        ttk.Button(dialog, text="Apply", command=apply).pack(pady=8)

    def _set_step_wait(self):
        """Set wait settings for the selected step."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step first.")
            return

        step = self._recorder.steps[idx]

        dialog = tk.Toplevel(self)
        dialog.title("Step Wait Settings")
        dialog.geometry("350x200")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Configure wait behavior for this step:", font=("Segoe UI", 9, "bold")).pack(
            padx=8, pady=8, anchor=tk.W
        )

        # Wait for ready checkbox
        wait_ready_var = tk.BooleanVar(value=step.wait_for_ready)
        ttk.Checkbutton(
            dialog,
            text="Wait for element to be visible and clickable before action",
            variable=wait_ready_var,
        ).pack(padx=16, pady=4, anchor=tk.W)

        # Wait after action
        wait_frame = ttk.Frame(dialog)
        wait_frame.pack(fill=tk.X, padx=16, pady=8)

        ttk.Label(wait_frame, text="Wait after action completes:").pack(side=tk.LEFT)
        wait_after_var = tk.DoubleVar(value=step.wait_after_action)
        ttk.Spinbox(
            wait_frame, from_=0.0, to=10.0, increment=0.1,
            textvariable=wait_after_var, width=6
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(wait_frame, text="seconds").pack(side=tk.LEFT)

        # Apply to all steps option
        apply_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            dialog,
            text="Apply to all recorded steps",
            variable=apply_all_var,
        ).pack(padx=16, pady=4, anchor=tk.W)

        def apply():
            wait_ready = wait_ready_var.get()
            wait_after = wait_after_var.get()

            if apply_all_var.get():
                self._recorder.set_all_steps_wait(
                    wait_for_ready=wait_ready,
                    wait_after_action=wait_after,
                )
            else:
                self._recorder.update_step_wait_settings(
                    idx,
                    wait_for_ready=wait_ready,
                    wait_after_action=wait_after,
                )
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_frame, text="Apply", command=apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=4)

    def _add_type_text_step(self):
        """Add a Type Text step after the selected step (reuses its element)."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step whose element you want to type into.")
            return

        text = simpledialog.askstring(
            "Type Text",
            "Enter the text to type:",
            parent=self,
        )
        if text is None:
            return

        source_step = self._recorder.steps[idx]
        new_step = RecordedStep(
            step_number=0,  # will be renumbered
            action=ActionType.TYPE_TEXT,
            element_info=source_step.element_info,
            screen_x=source_step.screen_x,
            screen_y=source_step.screen_y,
            text_input=text,
        )
        self._recorder.insert_step_after(idx, new_step)
        self._refresh_step_list()

    def _add_wait_step(self):
        """Add a Wait For Element step after the selected step."""
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo("No Selection", "Select a step to wait for.")
            return

        source_step = self._recorder.steps[idx]
        new_step = RecordedStep(
            step_number=0,
            action=ActionType.WAIT_FOR_ELEMENT,
            element_info=source_step.element_info,
            screen_x=source_step.screen_x,
            screen_y=source_step.screen_y,
        )
        self._recorder.insert_step_after(idx, new_step)
        self._refresh_step_list()

    def _add_send_keys_step(self):
        """
        Add a Send Keys step after the selected step.
        
        Send Keys sends keystrokes to the currently focused element.
        Useful for typing text or sending keyboard shortcuts after a click.
        """
        idx = self._get_selected_index()
        if idx < 0:
            messagebox.showinfo(
                "No Selection", 
                "Select a step after which to add the Send Keys step."
            )
            return

        # Show dialog with help text about special keys
        text = simpledialog.askstring(
            "Send Keys",
            "Enter the keys to send:\n\n"
            "Special keys: {Enter}, {Tab}, {Escape}, {Backspace}\n"
            "Modifiers: {Ctrl}, {Alt}, {Shift} (e.g., {Ctrl}a)\n"
            "Function keys: {F1}..{F12}\n"
            "Arrow keys: {Up}, {Down}, {Left}, {Right}",
            parent=self,
        )
        if text is None:
            return

        # Get the source step (for positioning - though Send Keys doesn't need locator)
        source_step = self._recorder.steps[idx]
        
        # Create a minimal ElementInfo for Send Keys (it doesn't need element details)
        from src.core.element_inspector import ElementInfo
        send_keys_info = ElementInfo(
            name="(Send Keys)",
            control_type_name="Keyboard",
            automation_id="",
            class_name="",
            bounding_rect=(0, 0, 0, 0),
            path="",
        )
        
        new_step = RecordedStep(
            step_number=0,  # will be renumbered
            action=ActionType.SEND_KEYS,
            element_info=send_keys_info,
            screen_x=source_step.screen_x,
            screen_y=source_step.screen_y,
            text_input=text,
        )
        self._recorder.insert_step_after(idx, new_step)
        self._refresh_step_list()

    # ── Code generation ───────────────────────────────────

    def _get_generation_options(self) -> Optional[dict]:
        """Show options dialog before generating code."""
        dialog = tk.Toplevel(self)
        dialog.title("Code Generation Options")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        result = {"ok": False}

        ttk.Label(dialog, text="Task Name:").pack(padx=8, pady=(8, 2), anchor=tk.W)
        task_var = tk.StringVar(value="Recorded Interaction")
        ttk.Entry(dialog, textvariable=task_var).pack(fill=tk.X, padx=8)

        ttk.Label(dialog, text="Window Locator (optional):").pack(padx=8, pady=(8, 2), anchor=tk.W)
        win_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=win_var).pack(fill=tk.X, padx=8)

        vars_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Use locator variables", variable=vars_var).pack(
            padx=8, pady=4, anchor=tk.W
        )

        comments_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Include comments", variable=comments_var).pack(
            padx=8, anchor=tk.W
        )

        delays_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Include recorded delays", variable=delays_var).pack(
            padx=8, anchor=tk.W
        )

        kw_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Generate reusable keyword", variable=kw_var).pack(
            padx=8, anchor=tk.W
        )

        def ok():
            result["ok"] = True
            result["task_name"] = task_var.get() or "Recorded Interaction"
            result["window_locator"] = win_var.get()
            result["use_variables"] = vars_var.get()
            result["include_comments"] = comments_var.get()
            result["include_delays"] = delays_var.get()
            result["include_keyword"] = kw_var.get()
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=8, pady=12)
        ttk.Button(btn_frame, text="Generate", command=ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=4)

        self.wait_window(dialog)
        return result if result["ok"] else None

    def _generate_code(self):
        """Generate and display the .robot file content."""
        steps = self._recorder.steps
        if not steps:
            messagebox.showinfo("No Steps", "Record some steps first.")
            return

        opts = self._get_generation_options()
        if opts is None:
            return

        code = generate_robot_file(
            steps=steps,
            task_name=opts["task_name"],
            window_locator=opts["window_locator"],
            include_comments=opts["include_comments"],
            use_variables=opts["use_variables"],
            include_delays=opts["include_delays"],
            include_keyword=opts["include_keyword"],
        )

        # Show in a new window
        viewer = tk.Toplevel(self)
        viewer.title("Generated Robot Framework Code")
        viewer.geometry("800x600")

        text = tk.Text(viewer, font=("Consolas", 10), wrap=tk.NONE)
        vsb = ttk.Scrollbar(viewer, orient=tk.VERTICAL, command=text.yview)
        hsb = ttk.Scrollbar(viewer, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        viewer.grid_rowconfigure(0, weight=1)
        viewer.grid_columnconfigure(0, weight=1)

        text.insert("1.0", code)

        btn_frame = ttk.Frame(viewer)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

        def copy_all():
            viewer.clipboard_clear()
            viewer.clipboard_append(code)
            viewer.update()

        ttk.Button(btn_frame, text="Copy All", command=copy_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Close", command=viewer.destroy).pack(side=tk.RIGHT, padx=4)

    def _save_robot_file(self):
        """Save generated code directly to a .robot file."""
        steps = self._recorder.steps
        if not steps:
            messagebox.showinfo("No Steps", "Record some steps first.")
            return

        opts = self._get_generation_options()
        if opts is None:
            return

        path = filedialog.asksaveasfilename(
            title="Save Robot Framework File",
            defaultextension=".robot",
            filetypes=[
                ("Robot Framework", "*.robot"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        code = generate_robot_file(
            steps=steps,
            task_name=opts["task_name"],
            window_locator=opts["window_locator"],
            include_comments=opts["include_comments"],
            use_variables=opts["use_variables"],
            include_delays=opts["include_delays"],
            include_keyword=opts["include_keyword"],
        )

        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        messagebox.showinfo("Saved", f"Robot file saved to:\n{path}")

    def _copy_keyword(self):
        """Copy just the keyword block to clipboard."""
        steps = self._recorder.steps
        if not steps:
            messagebox.showinfo("No Steps", "Record some steps first.")
            return

        code = generate_keyword_only(
            steps=steps,
            keyword_name="Recorded Interaction",
            use_variables=False,
            include_comments=True,
        )

        try:
            self.clipboard_clear()
            self.clipboard_append(code)
            self.update()
            messagebox.showinfo("Copied", "Keyword block copied to clipboard.")
        except Exception:
            pass

    # ── Playback controls ─────────────────────────────────

    def _play_all(self):
        """Execute all recorded steps."""
        steps = self._recorder.steps
        if not steps:
            messagebox.showinfo("No Steps", "Record some steps first.")
            return

        if self._executor.is_running:
            messagebox.showinfo("Running", "Execution is already in progress.")
            return

        # Update execution settings
        self._executor.delay_between_steps = self._delay_var.get()
        self._executor.auto_wait_for_ready = self._auto_wait_var.get()
        self._executor.auto_wait_after_action = self._wait_after_var.get()

        # Clear previous status
        self._clear_step_status()

        # Update button states
        self._set_playback_running(True)

        # Run execution
        self._executor.execute_all(steps)

    def _play_step(self):
        """Execute a single step (selected or next)."""
        steps = self._recorder.steps
        if not steps:
            messagebox.showinfo("No Steps", "Record some steps first.")
            return

        # If paused, resume with single step then pause again
        if self._executor.is_paused:
            idx = self._executor.current_step_index + 1
            if idx < len(steps):
                self._executor.delay_between_steps = 0
                result = self._executor.execute_single_step(steps[idx])
                self._on_execution_step_complete(idx, result)
            return

        # Get selected step index or use 0
        idx = self._get_selected_index()
        if idx < 0:
            idx = 0

        if idx >= len(steps):
            messagebox.showinfo("Done", "No more steps to execute.")
            return

        # Execute single step
        self._executor.delay_between_steps = 0
        self._set_playback_running(True)

        def _run_single():
            import ctypes
            try:
                ctypes.windll.ole32.CoInitialize(0)
            except Exception:
                pass

            result = self._executor.execute_single_step(steps[idx])
            self.after(0, lambda: self._on_single_step_complete(idx, result))

        import threading
        threading.Thread(target=_run_single, daemon=True).start()

    def _on_single_step_complete(self, idx: int, result: StepResult):
        """Handle completion of a single step execution."""
        self._on_execution_step_complete(idx, result)
        self._set_playback_running(False)

        # Select next step
        items = self._step_tree.get_children()
        if idx + 1 < len(items):
            self._step_tree.selection_set(items[idx + 1])
            self._step_tree.see(items[idx + 1])

    def _pause_execution(self):
        """Pause execution after the current step."""
        if self._executor.is_running:
            self._executor.pause()
            self._pause_btn.config(text="▶ Resume")
            self._pause_btn.config(command=self._resume_execution)
            self._exec_status_var.set("Paused")

    def _resume_execution(self):
        """Resume paused execution."""
        steps = self._recorder.steps
        if self._executor.is_paused:
            self._executor.delay_between_steps = self._delay_var.get()
            self._executor.resume(steps)
            self._pause_btn.config(text="⏸ Pause")
            self._pause_btn.config(command=self._pause_execution)

    def _stop_execution(self):
        """Stop execution."""
        self._executor.stop()
        self._set_playback_running(False)
        self._exec_status_var.set("Stopped")

    def _set_playback_running(self, running: bool):
        """Update UI for running/stopped state."""
        if running:
            self._play_btn.config(state=tk.DISABLED)
            self._step_btn.config(state=tk.DISABLED)
            self._pause_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.NORMAL)
            self._record_btn.config(state=tk.DISABLED)
        else:
            self._play_btn.config(state=tk.NORMAL)
            self._step_btn.config(state=tk.NORMAL)
            self._pause_btn.config(state=tk.DISABLED)
            self._pause_btn.config(text="⏸ Pause")
            self._pause_btn.config(command=self._pause_execution)
            self._stop_btn.config(state=tk.DISABLED)
            self._record_btn.config(state=tk.NORMAL)

    def _clear_step_status(self):
        """Clear status from all steps in the tree."""
        for item_id in self._step_tree.get_children():
            values = list(self._step_tree.item(item_id, "values"))
            if len(values) >= 5:
                values[4] = ""
            self._step_tree.item(item_id, values=tuple(values), tags=())

    def _update_step_status(self, index: int, status: str, tag: str = ""):
        """Update the status column for a specific step."""
        items = self._step_tree.get_children()
        if index < len(items):
            item_id = items[index]
            values = list(self._step_tree.item(item_id, "values"))
            if len(values) >= 5:
                values[4] = status
            else:
                values = list(values) + [""] * (5 - len(values))
                values[4] = status
            self._step_tree.item(item_id, values=tuple(values), tags=(tag,) if tag else ())
            self._step_tree.see(item_id)

    # ── Execution callbacks ───────────────────────────────

    def _on_execution_step_start(self, index: int, step: RecordedStep):
        """Called when a step is about to execute."""
        def _update():
            self._update_step_status(index, "Running...", "running")
            # Highlight the element being acted on
            if self._on_highlight_step:
                self._on_highlight_step(step)
        self.after(0, _update)

    def _on_execution_step_complete(self, index: int, result: StepResult):
        """Called when a step has finished executing."""
        def _update():
            if result.status == ExecutionStatus.SUCCESS:
                self._update_step_status(index, "✓ OK", "success")
            elif result.status == ExecutionStatus.FAILED:
                self._update_step_status(index, f"✗ {result.message[:20]}", "failed")
            elif result.status == ExecutionStatus.SKIPPED:
                self._update_step_status(index, "Skipped", "skipped")
        self.after(0, _update)

    def _on_execution_complete(self, results: list[StepResult]):
        """Called when all steps have finished executing."""
        def _update():
            self._set_playback_running(False)
            success = sum(1 for r in results if r.status == ExecutionStatus.SUCCESS)
            failed = sum(1 for r in results if r.status == ExecutionStatus.FAILED)
            self._exec_status_var.set(f"Done: {success} OK, {failed} failed")
            if failed == 0:
                self._exec_status_label.config(foreground="green")
            else:
                self._exec_status_label.config(foreground="red")
        self.after(0, _update)

    def _on_execution_status(self, message: str):
        """Called with status updates during execution."""
        def _update():
            self._exec_status_var.set(message[:50])
        self.after(0, _update)
