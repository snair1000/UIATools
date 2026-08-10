"""
repository_panel.py - GUI panel for the screen repository.

Provides:
  - New/Open repository (.db file)
  - Capture Current Window into the repository (with label prompt)
  - Screen list with metadata
  - Delete screen, view stored element tree
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from typing import Callable, Optional

from src.repository.screen_db import ScreenRepository, ScreenRecord


class RepositoryPanel(ttk.Frame):
    """
    Panel for managing the screen repository.

    The panel does not own the repository - the main app opens/closes it
    and pushes it in via set_repository(). Capture is delegated back to
    the app via on_capture (the app owns the target window and tree walk).
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_capture: Optional[Callable[[], None]] = None,
        on_repository_changed: Optional[Callable[[Optional[ScreenRepository]], None]] = None,
    ):
        super().__init__(parent)
        self._repo: Optional[ScreenRepository] = None
        self._on_capture = on_capture
        self._on_repository_changed = on_repository_changed
        self._setup_ui()

    @property
    def repository(self) -> Optional[ScreenRepository]:
        return self._repo

    def set_repository(self, repo: Optional[ScreenRepository]):
        """Attach an open repository and refresh the view."""
        self._repo = repo
        self._update_repo_label()
        self.refresh_screens()

    # ── UI setup ──────────────────────────────────────────────

    def _setup_ui(self):
        # Top controls
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        ttk.Button(ctrl_frame, text="🆕 New Repository", command=self._new_repository).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ctrl_frame, text="📂 Open Repository", command=self._open_repository).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self._capture_btn = ttk.Button(
            ctrl_frame, text="📸 Capture Window...", command=self._capture_clicked
        )
        self._capture_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl_frame, text="🗑 Delete Screen", command=self._delete_screen).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ctrl_frame, text="🔄 Refresh", command=self.refresh_screens).pack(
            side=tk.LEFT, padx=2
        )

        # Repository path label
        self._repo_var = tk.StringVar(value="No repository open")
        ttk.Label(self, textvariable=self._repo_var, foreground="gray").pack(
            fill=tk.X, padx=6, pady=2, anchor=tk.W
        )

        # Screen list
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        columns = ("label", "title", "process", "elements", "depth", "captured")
        self._screen_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="browse"
        )
        self._screen_tree.heading("label", text="Label")
        self._screen_tree.heading("title", text="Window Title")
        self._screen_tree.heading("process", text="Process")
        self._screen_tree.heading("elements", text="Elements")
        self._screen_tree.heading("depth", text="Depth")
        self._screen_tree.heading("captured", text="Captured At")
        self._screen_tree.column("label", width=160)
        self._screen_tree.column("title", width=200)
        self._screen_tree.column("process", width=110)
        self._screen_tree.column("elements", width=70, anchor=tk.E)
        self._screen_tree.column("depth", width=50, anchor=tk.E)
        self._screen_tree.column("captured", width=140)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._screen_tree.yview)
        self._screen_tree.config(yscrollcommand=sb.set)
        self._screen_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._screen_tree.bind("<Double-1>", lambda e: self._show_screen_details())

        # Bottom: details
        detail_frame = ttk.LabelFrame(self, text="Screen Details")
        detail_frame.pack(fill=tk.X, padx=4, pady=4)
        self._detail_text = tk.Text(
            detail_frame, height=6, font=("Consolas", 9), wrap=tk.WORD, state=tk.DISABLED
        )
        self._detail_text.pack(fill=tk.X, padx=4, pady=4)

    # ── Repository open/create ───────────────────────────────

    def _new_repository(self):
        path = filedialog.asksaveasfilename(
            title="Create Screen Repository",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        self._switch_repository(path)

    def _open_repository(self):
        path = filedialog.askopenfilename(
            title="Open Screen Repository",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        self._switch_repository(path)

    def _switch_repository(self, path: str):
        try:
            repo = ScreenRepository(path)
        except Exception as e:
            messagebox.showerror("Repository", f"Failed to open repository:\n{e}")
            return
        if self._repo:
            self._repo.close()
        self._repo = repo
        self._update_repo_label()
        self.refresh_screens()
        if self._on_repository_changed:
            self._on_repository_changed(repo)

    def _update_repo_label(self):
        if self._repo:
            self._repo_var.set(f"Repository: {self._repo.db_path}")
        else:
            self._repo_var.set("No repository open")

    # ── Screen list ──────────────────────────────────────────

    def refresh_screens(self):
        """Reload the screen list from the repository."""
        self._screen_tree.delete(*self._screen_tree.get_children())
        if not self._repo:
            return
        try:
            screens = self._repo.list_screens()
        except Exception as e:
            messagebox.showerror("Repository", f"Failed to list screens:\n{e}")
            return
        for s in screens:
            self._screen_tree.insert(
                "",
                "end",
                iid=str(s.screen_id),
                values=(
                    s.label,
                    s.window_title,
                    s.process_name,
                    s.element_count,
                    s.max_depth,
                    s.captured_at,
                ),
            )

    def selected_screen_id(self) -> Optional[int]:
        """Return the screen_id of the selected row, or None."""
        sel = self._screen_tree.selection()
        return int(sel[0]) if sel else None

    def _delete_screen(self):
        screen_id = self.selected_screen_id()
        if not self._repo or screen_id is None:
            return
        screen = self._repo.get_screen(screen_id)
        if not screen:
            return
        if not messagebox.askyesno(
            "Delete Screen", f"Delete screen '{screen.label}' and all its elements?"
        ):
            return
        self._repo.delete_screen(screen_id)
        self.refresh_screens()

    def _show_screen_details(self):
        screen_id = self.selected_screen_id()
        if not self._repo or screen_id is None:
            return
        screen = self._repo.get_screen(screen_id)
        if not screen:
            return
        lines = [
            f"Label:        {screen.label}",
            f"Window Title: {screen.window_title}",
            f"Process:      {screen.process_name}",
            f"Class:        {screen.class_name}",
            f"Window Rect:  {screen.window_rect}",
            f"Max Depth:    {screen.max_depth}",
            f"Elements:     {screen.element_count}",
            f"Captured At:  {screen.captured_at}",
        ]
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert("1.0", "\n".join(lines))
        self._detail_text.config(state=tk.DISABLED)

    # ── Capture ──────────────────────────────────────────────

    def _capture_clicked(self):
        if not self._repo:
            messagebox.showinfo(
                "Repository", "Create or open a repository first (.db file)."
            )
            return
        if self._on_capture:
            self._on_capture()

    def ask_screen_label(self, default: str = "") -> Optional[str]:
        """Prompt the user for a screen label. Returns None if cancelled."""
        return simpledialog.askstring(
            "Screen Label",
            "Enter a label for this screen (e.g. 'Login Screen'):",
            initialvalue=default,
            parent=self,
        )
