"""
property_panel.py - Element property display panel.

Shows all UIA properties of the selected element in a read-only
table, with copy-to-clipboard and export support.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from src.core.uia_wrapper import ElementInfo


class PropertyPanel(ttk.Frame):
    """
    Panel that displays UIA element properties in a table format.
    Includes copy buttons for key properties and full export.
    """

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self._current_info: Optional[ElementInfo] = None
        self._setup_ui()

    def _setup_ui(self):
        """Build the property panel UI."""
        # Header with quick-copy buttons
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=2, pady=2)

        ttk.Label(header, text="Element Properties", font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT
        )

        btn_frame = ttk.Frame(header)
        btn_frame.pack(side=tk.RIGHT)

        ttk.Button(btn_frame, text="Copy Path", command=self._copy_path).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Copy Name", command=self._copy_name).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Copy AutomationId", command=self._copy_aid).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Copy All", command=self._copy_all).pack(
            side=tk.LEFT, padx=2
        )

        # Quick info labels
        info_frame = ttk.LabelFrame(self, text="Quick Info")
        info_frame.pack(fill=tk.X, padx=2, pady=2)

        self._path_var = tk.StringVar(value="(no element selected)")
        self._name_var = tk.StringVar(value="")
        self._aid_var = tk.StringVar(value="")
        self._class_var = tk.StringVar(value="")
        self._type_var = tk.StringVar(value="")
        self._value_var = tk.StringVar(value="")
        self._rect_var = tk.StringVar(value="")
        self._center_var = tk.StringVar(value="")

        labels = [
            ("Path:", self._path_var),
            ("Name:", self._name_var),
            ("AutomationId:", self._aid_var),
            ("ClassName:", self._class_var),
            ("Type:", self._type_var),
            ("Value:", self._value_var),
            ("BoundingRect:", self._rect_var),
            ("Center (x, y):", self._center_var),
        ]
        for i, (label_text, var) in enumerate(labels):
            ttk.Label(info_frame, text=label_text, font=("Consolas", 9, "bold")).grid(
                row=i, column=0, sticky="w", padx=4, pady=1
            )
            entry = ttk.Entry(info_frame, textvariable=var, state="readonly", font=("Consolas", 9))
            entry.grid(row=i, column=1, sticky="ew", padx=4, pady=1)
        info_frame.grid_columnconfigure(1, weight=1)

        # Full property table
        self._table_frame = ttk.LabelFrame(self, text="All Properties")
        self._table_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self._prop_tree = ttk.Treeview(
            self._table_frame,
            columns=("value",),
            show="tree headings",
            selectmode="browse",
        )
        self._prop_tree.heading("#0", text="Property", anchor=tk.W)
        self._prop_tree.heading("value", text="Value", anchor=tk.W)
        self._prop_tree.column("#0", width=180, minwidth=100)
        self._prop_tree.column("value", width=400, minwidth=200)

        vsb = ttk.Scrollbar(self._table_frame, orient=tk.VERTICAL, command=self._prop_tree.yview)
        self._prop_tree.configure(yscrollcommand=vsb.set)

        self._prop_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._table_frame.grid_rowconfigure(0, weight=1)
        self._table_frame.grid_columnconfigure(0, weight=1)

        # Double-click to copy value
        self._prop_tree.bind("<Double-1>", self._on_prop_double_click)

    def show_element(self, info: ElementInfo):
        """Display the properties of the given element."""
        self._current_info = info

        # Update quick info
        self._path_var.set(info.path or "(no path)")
        self._name_var.set(info.name)
        self._aid_var.set(info.automation_id)
        self._type_var.set(info.control_type_name)
        self._class_var.set(info.class_name)
        self._value_var.set(info.value)
        self._rect_var.set(
            f"({info.bounding_rect[0]}, {info.bounding_rect[1]}, "
            f"{info.bounding_rect[2]}, {info.bounding_rect[3]})"
        )
        self._center_var.set(f"({info.center_x}, {info.center_y})")

        # Update full property table
        self._prop_tree.delete(*self._prop_tree.get_children())
        props = info.to_dict()
        for key, value in props.items():
            self._prop_tree.insert("", "end", text=key, values=(str(value),))

    def clear(self):
        """Clear all displayed properties."""
        self._current_info = None
        self._path_var.set("(no element selected)")
        self._name_var.set("")
        self._aid_var.set("")
        self._class_var.set("")
        self._type_var.set("")
        self._value_var.set("")
        self._rect_var.set("")
        self._center_var.set("")
        self._prop_tree.delete(*self._prop_tree.get_children())

    def _copy_path(self):
        """Copy the element path to clipboard."""
        if self._current_info:
            self._copy_to_clipboard(self._current_info.path)

    def _copy_name(self):
        """Copy the element name to clipboard."""
        if self._current_info:
            self._copy_to_clipboard(self._current_info.name)

    def _copy_aid(self):
        """Copy the AutomationId to clipboard."""
        if self._current_info:
            self._copy_to_clipboard(self._current_info.automation_id)

    def _copy_all(self):
        """Copy all properties to clipboard as text."""
        if self._current_info:
            props = self._current_info.to_dict()
            lines = [f"{k}: {v}" for k, v in props.items()]
            self._copy_to_clipboard("\n".join(lines))

    def _copy_to_clipboard(self, text: str):
        """Copy text to the system clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
        except Exception:
            pass

    def _on_prop_double_click(self, event):
        """Copy the selected property value to clipboard on double-click."""
        selection = self._prop_tree.selection()
        if selection:
            values = self._prop_tree.item(selection[0], "values")
            if values:
                self._copy_to_clipboard(str(values[0]))

    def set_compact_mode(self, compact: bool):
        """Toggle between compact (locators only) and full property display."""
        if compact:
            self._table_frame.pack_forget()
        else:
            self._table_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
