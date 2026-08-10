"""
coord_recorder_panel.py - GUI panel for the lightweight coordinate recorder.

Provides:
  - Start/Stop/Pause capture controls (pause hotkey: Ctrl+Shift+F12)
  - Event list (clicks, typed text, special keys) with window context
  - Right-click: delete or redact events
  - Save/Load recordings to the screen repository
  - Generate Script with AI (delegated to the main app)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Callable, Optional

from src.recording.coord_recorder import CoordRecorder
from src.repository.screen_db import RecordedEvent, ScreenRepository


class CoordRecorderPanel(ttk.Frame):
    """Panel for recording raw x,y clicks + keystrokes."""

    def __init__(
        self,
        parent: tk.Widget,
        on_generate: Optional[Callable[[list[RecordedEvent]], None]] = None,
    ):
        super().__init__(parent)
        self._on_generate = on_generate
        self._repo: Optional[ScreenRepository] = None
        self._recorder = CoordRecorder(
            on_event=self._on_event_from_hook,
            on_pause_toggle=self._on_pause_from_hook,
        )
        self._setup_ui()

    def set_repository(self, repo: Optional[ScreenRepository]):
        """Attach the open repository (for save/load of recordings)."""
        self._repo = repo

    @property
    def events(self) -> list[RecordedEvent]:
        return self._recorder.events

    # ── UI setup ──────────────────────────────────────────────

    def _setup_ui(self):
        # Controls
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        self._start_btn = ttk.Button(
            ctrl_frame, text="⏺ Start Capture", command=self._toggle_capture
        )
        self._start_btn.pack(side=tk.LEFT, padx=2)

        self._pause_btn = ttk.Button(
            ctrl_frame, text="⏸ Pause", command=self._toggle_pause, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl_frame, text="🗑 Clear", command=self._clear_events).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(ctrl_frame, text="💾 Save Recording", command=self._save_recording).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ctrl_frame, text="📂 Load Recording", command=self._load_recording).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self._generate_btn = ttk.Button(
            ctrl_frame, text="🤖 Generate Script with AI...", command=self._generate_clicked
        )
        self._generate_btn.pack(side=tk.LEFT, padx=2)

        self._status_var = tk.StringVar(value="Not capturing")
        self._status_label = ttk.Label(
            ctrl_frame, textvariable=self._status_var, foreground="gray"
        )
        self._status_label.pack(side=tk.RIGHT, padx=8)

        # Hint
        ttk.Label(
            self,
            text="Captures raw clicks + keystrokes with window context. "
            "Pause hotkey: Ctrl+Shift+F12. Right-click an event to delete/redact.",
            foreground="gray",
        ).pack(fill=tk.X, padx=6, pady=2, anchor=tk.W)

        # Event list
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        columns = ("time", "type", "detail", "window", "process")
        self._event_tree = ttk.Treeview(
            list_frame, columns=columns, show="tree headings", selectmode="browse"
        )
        self._event_tree.heading("#0", text="#")
        self._event_tree.heading("time", text="Time (s)")
        self._event_tree.heading("type", text="Type")
        self._event_tree.heading("detail", text="Detail")
        self._event_tree.heading("window", text="Window")
        self._event_tree.heading("process", text="Process")
        self._event_tree.column("#0", width=40, stretch=False)
        self._event_tree.column("time", width=70, anchor=tk.E, stretch=False)
        self._event_tree.column("type", width=60, stretch=False)
        self._event_tree.column("detail", width=340)
        self._event_tree.column("window", width=200)
        self._event_tree.column("process", width=100)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._event_tree.yview)
        self._event_tree.config(yscrollcommand=sb.set)
        self._event_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._event_tree.tag_configure("redacted", foreground="orange")
        self._event_tree.tag_configure("click", foreground="#0055aa")

        # Context menu
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Redact Text", command=self._redact_selected)
        self._menu.add_command(label="Delete Event", command=self._delete_selected)
        self._event_tree.bind("<Button-3>", self._show_context_menu)

    # ── Capture control ───────────────────────────────────────

    def _toggle_capture(self):
        if self._recorder.is_recording:
            self._recorder.stop()
            self._start_btn.config(text="⏺ Start Capture")
            self._pause_btn.config(state=tk.DISABLED, text="⏸ Pause")
            self._status_var.set(f"Stopped ({self._recorder.event_count} events)")
            self._status_label.config(foreground="gray")
            self._refresh_event_list()
        else:
            self._recorder.start()
            self._start_btn.config(text="⏹ Stop Capture")
            self._pause_btn.config(state=tk.NORMAL)
            self._status_var.set("🔴 CAPTURING...")
            self._status_label.config(foreground="red")

    def _toggle_pause(self):
        self._recorder.toggle_pause()

    def _on_pause_from_hook(self, paused: bool):
        """Called from hook thread when pause is toggled."""
        self.after(0, self._update_pause_ui, paused)

    def _update_pause_ui(self, paused: bool):
        if paused:
            self._pause_btn.config(text="▶ Resume")
            self._status_var.set("⏸ PAUSED (Ctrl+Shift+F12 to resume)")
            self._status_label.config(foreground="orange")
        else:
            self._pause_btn.config(text="⏸ Pause")
            if self._recorder.is_recording:
                self._status_var.set("🔴 CAPTURING...")
                self._status_label.config(foreground="red")

    def _clear_events(self):
        if self._recorder.event_count > 0:
            if not messagebox.askyesno("Clear", "Delete all captured events?"):
                return
        self._recorder.clear()
        self._refresh_event_list()
        self._status_var.set("Cleared")

    # ── Event list ────────────────────────────────────────────

    def _on_event_from_hook(self, event: RecordedEvent):
        """Called from hook threads - marshal to the tkinter main loop."""
        self.after(0, self._add_event_row, event)

    def _add_event_row(self, ev: RecordedEvent):
        self._event_tree.insert(
            "",
            "end",
            iid=str(ev.seq),
            text=str(ev.seq),
            values=self._event_values(ev),
            tags=self._event_tags(ev),
        )
        self._event_tree.see(str(ev.seq))
        if self._recorder.is_recording and not self._recorder.is_paused:
            self._status_var.set(f"🔴 CAPTURING... ({self._recorder.event_count} events)")

    def _event_values(self, ev: RecordedEvent) -> tuple:
        if ev.event_type == "click":
            detail = f"{ev.button} click @ ({ev.x}, {ev.y})"
            rect = ev.window_rect
            if rect and rect != (0, 0, 0, 0):
                rel_x = ev.x - rect[0]
                rel_y = ev.y - rect[1]
                detail += f"  rel ({rel_x}, {rel_y})  win rect {tuple(rect)}"
        elif ev.event_type == "keys":
            detail = f'typed "{ev.text}"'
        else:
            detail = f"key [{ev.vk_name}]"
        return (
            f"{ev.t_offset:.1f}",
            ev.event_type,
            detail,
            ev.window_title[:40],
            ev.process_name,
        )

    def _event_tags(self, ev: RecordedEvent) -> tuple:
        if ev.redacted:
            return ("redacted",)
        if ev.event_type == "click":
            return ("click",)
        return ()

    def _refresh_event_list(self):
        self._event_tree.delete(*self._event_tree.get_children())
        for ev in self._recorder.events:
            self._event_tree.insert(
                "",
                "end",
                iid=str(ev.seq),
                text=str(ev.seq),
                values=self._event_values(ev),
                tags=self._event_tags(ev),
            )

    def _show_context_menu(self, event):
        item = self._event_tree.identify_row(event.y)
        if item:
            self._event_tree.selection_set(item)
            self._menu.post(event.x_root, event.y_root)

    def _selected_seq(self) -> Optional[int]:
        sel = self._event_tree.selection()
        return int(sel[0]) if sel else None

    def _redact_selected(self):
        seq = self._selected_seq()
        if seq is None:
            return
        self._recorder.redact_event(seq)
        self._refresh_event_list()

    def _delete_selected(self):
        seq = self._selected_seq()
        if seq is None:
            return
        self._recorder.remove_event(seq)
        self._refresh_event_list()

    # ── Save / Load ───────────────────────────────────────────

    def _save_recording(self):
        if not self._repo:
            messagebox.showinfo("Recording", "Open a repository first (Repository tab).")
            return
        events = self._recorder.events
        if not events:
            messagebox.showinfo("Recording", "No events to save.")
            return
        label = simpledialog.askstring(
            "Save Recording", "Enter a label for this recording:", parent=self
        )
        if not label:
            return
        try:
            recording_id = self._repo.save_recording(label, events)
        except Exception as e:
            messagebox.showerror("Recording", f"Failed to save recording:\n{e}")
            return
        self._status_var.set(f"Saved recording '{label}' (id {recording_id})")

    def _load_recording(self):
        if not self._repo:
            messagebox.showinfo("Recording", "Open a repository first (Repository tab).")
            return
        recordings = self._repo.list_recordings()
        if not recordings:
            messagebox.showinfo("Recording", "No recordings in this repository.")
            return

        # Simple picker dialog
        dlg = tk.Toplevel(self)
        dlg.title("Load Recording")
        dlg.geometry("500x300")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        lb = tk.Listbox(dlg, font=("Consolas", 9))
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for r in recordings:
            lb.insert(
                tk.END,
                f"[{r['recording_id']}] {r['label']} - {r['event_count']} events ({r['created_at']})",
            )

        def _do_load():
            sel = lb.curselection()
            if not sel:
                return
            rec = recordings[sel[0]]
            events = self._repo.load_recording(rec["recording_id"])
            self._recorder.clear()
            self._recorder._events = events  # restore into recorder state
            self._recorder._seq = max((ev.seq for ev in events), default=0)
            self._refresh_event_list()
            self._status_var.set(f"Loaded recording '{rec['label']}' ({len(events)} events)")
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(btns, text="Load", command=_do_load).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)
        lb.bind("<Double-1>", lambda e: _do_load())

    # ── Generate ──────────────────────────────────────────────

    def _generate_clicked(self):
        if self._recorder.is_recording:
            messagebox.showinfo("Generate", "Stop capturing first.")
            return
        events = self._recorder.events
        if not events:
            messagebox.showinfo("Generate", "No captured events to generate from.")
            return
        if not self._repo:
            messagebox.showinfo("Generate", "Open a repository first (Repository tab).")
            return
        if self._on_generate:
            self._on_generate(events)

    def shutdown(self):
        """Stop hooks on app close."""
        if self._recorder.is_recording:
            self._recorder.stop()
