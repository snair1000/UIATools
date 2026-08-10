"""
generation_review_dialog.py - Review UI for AI-generated scripts.

Runs the ScriptBuilder pipeline on a background thread with progress,
then lets the user:
  - review each resolved step (locator, action, confidence),
  - swap the locator from the candidate element's other strategies,
  - TEST RUN the steps live against the target app (all steps or from
    the selected step) and see per-step pass/fail, fix, and re-run,
  - preview the final .robot text,
  - save/copy the script (accepted locators are persisted for the
    feedback loop).
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

from src.ai.script_builder import GeneratedStep, ScriptBuilder
from src.core.step_executor import ExecutionStatus, StepExecutor
from src.repository.screen_db import RecordedEvent


class GenerationReviewDialog(tk.Toplevel):
    """Modal dialog that generates, reviews, and exports an AI script."""

    def __init__(
        self,
        parent: tk.Widget,
        builder: ScriptBuilder,
        events: list[RecordedEvent],
        task_name: str = "AI Generated Task",
    ):
        super().__init__(parent)
        self.title("AI Script Generation")
        self.geometry("980x720")
        self.minsize(760, 560)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._builder = builder
        self._events = events
        self._task_name = task_name
        self._steps: list[GeneratedStep] = []
        self._cancelled = False

        # Live test-run state
        self._executor = StepExecutor()
        self._run_thread: Optional[threading.Thread] = None
        self._run_stop = threading.Event()

        self._setup_ui()
        self._start_generation()

    # ── UI ────────────────────────────────────────────────────

    def _setup_ui(self):
        # Progress bar (top)
        prog_frame = ttk.Frame(self, padding=8)
        prog_frame.pack(fill=tk.X)
        self._progress_var = tk.StringVar(value="Starting generation...")
        ttk.Label(prog_frame, textvariable=self._progress_var).pack(side=tk.LEFT)
        self._progress_bar = ttk.Progressbar(prog_frame, mode="determinate", length=240)
        self._progress_bar.pack(side=tk.RIGHT)

        # Bottom-anchored rows are packed first (side=BOTTOM, reverse visual
        # order) so the expanding paned window can never push them off-screen.

        # Bottom buttons
        btn_row = ttk.Frame(self, padding=8)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X)
        self._save_btn = ttk.Button(
            btn_row, text="\U0001f4be Save .robot...", command=self._save_robot, state=tk.DISABLED
        )
        self._save_btn.pack(side=tk.LEFT, padx=2)
        self._copy_btn = ttk.Button(
            btn_row, text="\U0001f4cb Copy to Clipboard", command=self._copy_robot, state=tk.DISABLED
        )
        self._copy_btn.pack(side=tk.LEFT, padx=2)
        self._regen_btn = ttk.Button(
            btn_row, text="\U0001f504 Refresh Preview", command=self._refresh_preview, state=tk.DISABLED
        )
        self._regen_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self._run_btn = ttk.Button(
            btn_row, text="\u25b6 Test Run", command=lambda: self._start_test_run(0),
            state=tk.DISABLED,
        )
        self._run_btn.pack(side=tk.LEFT, padx=2)
        self._run_from_btn = ttk.Button(
            btn_row, text="\u25b6 Run from Selected",
            command=self._run_from_selected, state=tk.DISABLED,
        )
        self._run_from_btn.pack(side=tk.LEFT, padx=2)
        self._stop_btn = ttk.Button(
            btn_row, text="\u23f9 Stop", command=self._stop_test_run, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(btn_row, text="Close", command=self._close).pack(side=tk.RIGHT, padx=2)

        # Reason-with-AI row: show the AI's reasoning and let the user push back
        ai_frame = ttk.LabelFrame(self, text="Reason with AI (selected step)", padding=(8, 4))
        ai_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 0))
        self._reasoning_var = tk.StringVar(value="Select a step to see the AI's reasoning.")
        ttk.Label(
            ai_frame,
            textvariable=self._reasoning_var,
            foreground="#555555",
            wraplength=920,
            justify=tk.LEFT,
        ).pack(fill=tk.X)
        feedback_row = ttk.Frame(ai_frame)
        feedback_row.pack(fill=tk.X, pady=(4, 0))
        self._feedback_var = tk.StringVar()
        feedback_entry = ttk.Entry(feedback_row, textvariable=self._feedback_var)
        feedback_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        feedback_entry.bind("<Return>", lambda e: self._refine_selected_step())
        self._refine_btn = ttk.Button(
            feedback_row,
            text="\U0001f9e0 Ask AI to Reconsider",
            command=self._refine_selected_step,
            state=tk.DISABLED,
        )
        self._refine_btn.pack(side=tk.LEFT, padx=(4, 0))

        # Locator editor row
        edit_frame = ttk.Frame(self, padding=(8, 0))
        edit_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(edit_frame, text="Locator for selected step:").pack(side=tk.LEFT)
        self._locator_var = tk.StringVar()
        self._locator_combo = ttk.Combobox(edit_frame, textvariable=self._locator_var, width=60)
        self._locator_combo.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(edit_frame, text="Apply", command=self._apply_locator).pack(side=tk.LEFT, padx=2)

        # Paned: steps table (top) / robot preview (bottom)
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Steps table
        steps_frame = ttk.LabelFrame(paned, text="Resolved Steps")
        paned.add(steps_frame, weight=1)

        columns = ("action", "locator", "text", "confidence", "status")
        self._step_tree = ttk.Treeview(
            steps_frame, columns=columns, show="tree headings", selectmode="browse"
        )
        self._step_tree.heading("#0", text="#")
        self._step_tree.heading("action", text="Action")
        self._step_tree.heading("locator", text="Locator")
        self._step_tree.heading("text", text="Text")
        self._step_tree.heading("confidence", text="Conf.")
        self._step_tree.heading("status", text="Status")
        self._step_tree.column("#0", width=40, stretch=False)
        self._step_tree.column("action", width=90, stretch=False)
        self._step_tree.column("locator", width=330)
        self._step_tree.column("text", width=140)
        self._step_tree.column("confidence", width=50, anchor=tk.E, stretch=False)
        self._step_tree.column("status", width=200)

        sb = ttk.Scrollbar(steps_frame, orient=tk.VERTICAL, command=self._step_tree.yview)
        self._step_tree.config(yscrollcommand=sb.set)
        self._step_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._step_tree.tag_configure("review", foreground="#b06000")
        self._step_tree.tag_configure("error", foreground="red")
        self._step_tree.tag_configure("ok", foreground="#006600")
        self._step_tree.tag_configure("run_ok", foreground="#006600", background="#e8f5e8")
        self._step_tree.tag_configure("run_fail", foreground="red", background="#fdecec")
        self._step_tree.tag_configure("run_current", background="#fff8d6")
        self._step_tree.bind("<Double-1>", lambda e: self._edit_selected_locator())
        self._step_tree.bind("<<TreeviewSelect>>", lambda e: self._on_step_selected())

        # Robot preview
        preview_frame = ttk.LabelFrame(paned, text=".robot Preview")
        paned.add(preview_frame, weight=1)
        self._preview_text = tk.Text(preview_frame, font=("Consolas", 9), wrap=tk.NONE)
        psb = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self._preview_text.yview)
        self._preview_text.config(yscrollcommand=psb.set)
        self._preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        psb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Generation (background thread) ────────────────────────

    def _start_generation(self):
        def _progress(current: int, total: int, message: str):
            def _update():
                self._progress_var.set(message)
                self._progress_bar.config(maximum=total, value=current)

            self.after(0, _update)

        def _run():
            try:
                steps = self._builder.build_steps(
                    self._events,
                    progress=_progress,
                    cancel_check=lambda: self._cancelled,
                )
            except Exception as e:
                self.after(0, lambda: self._on_generation_failed(str(e)))
                return
            self.after(0, lambda: self._on_generation_done(steps))

        threading.Thread(target=_run, daemon=True).start()

    def _on_generation_failed(self, error: str):
        self._progress_var.set("Generation failed.")
        messagebox.showerror("AI Script Generation", error, parent=self)

    def _on_generation_done(self, steps: list[GeneratedStep]):
        self._steps = steps
        review_count = sum(1 for s in steps if s.needs_review)
        self._progress_var.set(
            f"Done: {len(steps)} steps, {review_count} need review."
        )
        self._progress_bar.config(value=self._progress_bar["maximum"])
        self._populate_steps()
        self._refresh_preview()
        self._save_btn.config(state=tk.NORMAL)
        self._copy_btn.config(state=tk.NORMAL)
        self._regen_btn.config(state=tk.NORMAL)
        self._refine_btn.config(state=tk.NORMAL)
        self._run_btn.config(state=tk.NORMAL)
        self._run_from_btn.config(state=tk.NORMAL)

    # ── Steps table ───────────────────────────────────────────

    def _populate_steps(self):
        self._step_tree.delete(*self._step_tree.get_children())
        for i, s in enumerate(self._steps):
            if s.error and not s.locator:
                tag, status = "error", s.error[:60]
            elif s.needs_review:
                tag, status = "review", (s.error or "Low confidence - review")[:60]
            else:
                tag, status = "ok", (s.keyword_name or "OK")[:60]
            if s.wait_before > 0:
                status = f"[wait {s.wait_before:.1f}s] {status}"[:60]
            self._step_tree.insert(
                "",
                "end",
                iid=str(i),
                text=str(i + 1),
                values=(
                    s.action.value,
                    s.locator,
                    s.text[:30],
                    f"{s.confidence:.2f}" if s.confidence else "",
                    status,
                ),
                tags=(tag,),
            )

    def _selected_step(self) -> Optional[GeneratedStep]:
        sel = self._step_tree.selection()
        if not sel:
            return None
        return self._steps[int(sel[0])]

    def _on_step_selected(self):
        step = self._selected_step()
        if not step:
            return
        options = []
        if step.element:
            # All strategies of the chosen element first, then other candidates
            for rec, strategies in step.candidates:
                for s in strategies:
                    options.append(s["locator"])
        self._locator_combo.config(values=options)
        self._locator_var.set(step.locator)
        if step.reasoning:
            self._reasoning_var.set(f"AI reasoning: {step.reasoning}")
        elif step.error:
            self._reasoning_var.set(f"Note: {step.error}")
        else:
            self._reasoning_var.set("No AI reasoning recorded for this step.")

    def _edit_selected_locator(self):
        self._on_step_selected()
        self._locator_combo.focus_set()

    def _apply_locator(self):
        sel = self._step_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        new_locator = self._locator_var.get().strip()
        if not new_locator:
            return
        self._steps[idx].locator = new_locator
        self._steps[idx].needs_review = False
        self._populate_steps()
        self._refresh_preview()

    # ── Reason with AI ────────────────────────────────────────

    def _refine_selected_step(self):
        sel = self._step_tree.selection()
        if not sel:
            messagebox.showinfo(
                "Reason with AI", "Select a step first.", parent=self
            )
            return
        feedback = self._feedback_var.get().strip()
        if not feedback:
            messagebox.showinfo(
                "Reason with AI",
                "Type your feedback first, e.g. 'That locator matches multiple "
                "buttons - use the AutomationId of the parent pane instead.'",
                parent=self,
            )
            return
        idx = int(sel[0])
        step = self._steps[idx]

        self._refine_btn.config(state=tk.DISABLED)
        self._progress_var.set(f"Asking AI to reconsider step {idx + 1}...")

        def _run():
            try:
                self._builder.refine_step(step, feedback)
            except Exception as e:
                self.after(0, lambda: self._on_refine_failed(str(e)))
                return
            self.after(0, lambda: self._on_refine_done(idx))

        threading.Thread(target=_run, daemon=True).start()

    def _on_refine_failed(self, error: str):
        self._refine_btn.config(state=tk.NORMAL)
        self._progress_var.set("AI reconsideration failed.")
        messagebox.showerror("Reason with AI", error, parent=self)

    def _on_refine_done(self, idx: int):
        self._refine_btn.config(state=tk.NORMAL)
        self._feedback_var.set("")
        self._populate_steps()
        self._step_tree.selection_set(str(idx))
        self._step_tree.see(str(idx))
        self._on_step_selected()
        self._refresh_preview()
        step = self._steps[idx]
        self._progress_var.set(
            f"Step {idx + 1} updated (confidence {step.confidence:.2f})."
        )

    # ── Live test run ─────────────────────────────────────

    def _run_from_selected(self):
        sel = self._step_tree.selection()
        if not sel:
            messagebox.showinfo("Test Run", "Select the step to start from.", parent=self)
            return
        self._start_test_run(int(sel[0]))

    def _start_test_run(self, start_gen_idx: int):
        if self._run_thread and self._run_thread.is_alive():
            return
        # Map generated steps -> executable RecordedSteps (respects the
        # current, possibly user-fixed, locators)
        mapped = self._builder.to_recorded_steps_mapped(self._steps)
        run_items = [(gi, rs) for gi, rs in mapped if gi >= start_gen_idx]
        if not run_items:
            messagebox.showinfo(
                "Test Run", "No executable steps (all skipped or unresolved).", parent=self
            )
            return
        if not messagebox.askokcancel(
            "Test Run",
            "The steps will be executed against the LIVE application.\n\n"
            "Bring the target application to the SAME SCREEN the recording "
            "started from, then press OK. Execution starts after a 3-second "
            "countdown.",
            parent=self,
        ):
            return

        # Clear previous run statuses for the steps about to run
        for gi, _ in run_items:
            self._set_run_status(gi, "", "")

        self._run_stop.clear()
        self._run_btn.config(state=tk.DISABLED)
        self._run_from_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)

        self._run_thread = threading.Thread(
            target=self._test_run_worker, args=(run_items,), daemon=True
        )
        self._run_thread.start()

    def _stop_test_run(self):
        self._run_stop.set()
        self._progress_var.set("Stopping after current step...")

    def _test_run_worker(self, run_items):
        """Worker thread: executes mapped steps one by one so results can be
        reported per review row and the run can honor per-step windows."""
        import uiautomation as auto

        com_inited = False
        try:
            auto.InitializeUIAutomationInCurrentThread()
            com_inited = True
        except Exception:
            pass

        failures = 0
        try:
            for i in (3, 2, 1):
                if self._run_stop.is_set():
                    return
                self.after(0, self._progress_var.set, f"Test run starts in {i}...")
                time.sleep(1.0)

            current_window = None
            for gi, rs in run_items:
                if self._run_stop.is_set():
                    self.after(0, self._progress_var.set, "Test run stopped.")
                    return

                if rs.window_locator and rs.window_locator != current_window:
                    self._executor.set_target_window_locator(rs.window_locator)
                    current_window = rs.window_locator

                self.after(0, self._mark_running, gi)
                result = self._executor.execute_single_step(rs)

                ok = result.status == ExecutionStatus.SUCCESS
                if not ok:
                    failures += 1
                self.after(
                    0,
                    self._set_run_status,
                    gi,
                    "run_ok" if ok else "run_fail",
                    f"Run: {'OK' if ok else 'FAILED'} - {result.message}"[:60],
                )

                if not ok:
                    self.after(
                        0,
                        self._progress_var.set,
                        f"Step {gi + 1} failed: {result.message[:80]} "
                        "- fix the locator and use 'Run from Selected'.",
                    )
                    self.after(0, self._select_step, gi)
                    return  # stop at first failure so the user can fix it

                if rs.delay_after > 0:
                    slept = 0.0
                    while slept < rs.delay_after and not self._run_stop.is_set():
                        time.sleep(min(0.2, rs.delay_after - slept))
                        slept += 0.2

            self.after(
                0,
                self._progress_var.set,
                f"Test run finished: {len(run_items)} steps, {failures} failed.",
            )
        finally:
            if com_inited:
                try:
                    auto.UninitializeUIAutomationInCurrentThread()
                except Exception:
                    pass
            self.after(0, self._on_test_run_ended)

    def _on_test_run_ended(self):
        self._run_btn.config(state=tk.NORMAL)
        self._run_from_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)

    def _mark_running(self, gen_idx: int):
        iid = str(gen_idx)
        if self._step_tree.exists(iid):
            self._step_tree.item(iid, tags=("run_current",))
            vals = list(self._step_tree.item(iid, "values"))
            vals[4] = "Running..."
            self._step_tree.item(iid, values=vals)
            self._step_tree.see(iid)

    def _set_run_status(self, gen_idx: int, tag: str, status: str):
        iid = str(gen_idx)
        if not self._step_tree.exists(iid):
            return
        vals = list(self._step_tree.item(iid, "values"))
        if status:
            vals[4] = status
            self._step_tree.item(iid, values=vals, tags=(tag,) if tag else ())
        else:
            # reset to pre-run appearance
            s = self._steps[gen_idx]
            if s.error and not s.locator:
                tag2, st = "error", s.error[:60]
            elif s.needs_review:
                tag2, st = "review", (s.error or "Low confidence - review")[:60]
            else:
                tag2, st = "ok", (s.keyword_name or "OK")[:60]
            vals[4] = st
            self._step_tree.item(iid, values=vals, tags=(tag2,))

    def _select_step(self, gen_idx: int):
        iid = str(gen_idx)
        if self._step_tree.exists(iid):
            self._step_tree.selection_set(iid)
            self._step_tree.see(iid)
            self._on_step_selected()

    # ── Preview / export ──────────────────────────────────────

    def _refresh_preview(self):
        try:
            robot_text = self._builder.generate_robot(self._steps, task_name=self._task_name)
        except Exception as e:
            robot_text = f"# Failed to render .robot: {e}"
        self._preview_text.delete("1.0", tk.END)
        self._preview_text.insert("1.0", robot_text)

    def _save_robot(self):
        path = filedialog.asksaveasfilename(
            title="Save .robot File",
            defaultextension=".robot",
            filetypes=[("Robot Framework", "*.robot"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._preview_text.get("1.0", tk.END))
        except OSError as e:
            messagebox.showerror("Save", f"Failed to save file:\n{e}", parent=self)
            return
        self._builder.record_accepted_locators(self._steps)
        messagebox.showinfo("Save", f"Saved: {path}", parent=self)

    def _copy_robot(self):
        self.clipboard_clear()
        self.clipboard_append(self._preview_text.get("1.0", tk.END))
        self._builder.record_accepted_locators(self._steps)
        self._progress_var.set("Copied to clipboard (locator choices recorded).")

    def _close(self):
        self._cancelled = True
        self._run_stop.set()
        self.destroy()
