"""
tree_panel.py - Tree view panel for the inspector GUI.

Displays the UIA element tree in a tkinter Treeview widget,
supporting lazy loading, search, and path display.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from src.core.tree_walker import TreeNode


class TreePanel(ttk.Frame):
    """
    A panel containing a Treeview widget that displays the UIA element tree.
    Supports lazy loading of children for performance.
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable[[TreeNode], None]] = None,
    ):
        super().__init__(parent)
        self._on_select = on_select
        self._node_map: dict[str, TreeNode] = {}  # treeview item id -> TreeNode
        self._setup_ui()

    def _setup_ui(self):
        """Build the tree panel UI."""
        # Search bar
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=2, pady=2)

        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_changed)
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        ttk.Button(search_frame, text="Clear", command=self._clear_search).pack(side=tk.RIGHT)

        # Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("path", "type", "automationid"),
            show="tree headings",
            selectmode="browse",
        )
        self._tree.heading("#0", text="Element", anchor=tk.W)
        self._tree.heading("path", text="Path", anchor=tk.W)
        self._tree.heading("type", text="Type", anchor=tk.W)
        self._tree.heading("automationid", text="AutomationId", anchor=tk.W)

        self._tree.column("#0", width=300, minwidth=150)
        self._tree.column("path", width=150, minwidth=80)
        self._tree.column("type", width=120, minwidth=60)
        self._tree.column("automationid", width=150, minwidth=80)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Bind selection event
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_double_click)

    def load_tree(self, root_node: TreeNode):
        """Load a tree starting from the given root node."""
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._insert_node("", root_node)

    def _insert_node(self, parent_item_id: str, node: TreeNode) -> str:
        """Insert a TreeNode into the Treeview widget."""
        info = node.element_info
        display_text = node.display_name

        item_id = self._tree.insert(
            parent_item_id,
            "end",
            text=display_text,
            values=(
                info.path,
                info.control_type_name,
                info.automation_id,
            ),
            open=(node.depth < 2),  # auto-expand first 2 levels
        )

        self._node_map[item_id] = node

        for child in node.children:
            self._insert_node(item_id, child)

        return item_id

    def select_node_by_path(self, path: str):
        """Select and reveal a tree node by its path string."""
        for item_id, node in self._node_map.items():
            if node.element_info.path == path:
                self._tree.selection_set(item_id)
                self._tree.focus(item_id)
                self._tree.see(item_id)
                # Ensure all ancestors are expanded
                parent_id = self._tree.parent(item_id)
                while parent_id:
                    self._tree.item(parent_id, open=True)
                    parent_id = self._tree.parent(parent_id)
                return

    def get_selected_node(self) -> Optional[TreeNode]:
        """Return the currently selected TreeNode."""
        selection = self._tree.selection()
        if selection:
            return self._node_map.get(selection[0])
        return None

    def _on_tree_select(self, event):
        """Handle tree selection change."""
        node = self.get_selected_node()
        if node and self._on_select:
            self._on_select(node)

    def _on_double_click(self, event):
        """Handle double-click on tree node."""
        # Same as select - could be extended for more actions
        node = self.get_selected_node()
        if node and self._on_select:
            self._on_select(node)

    def _on_search_changed(self, *args):
        """Filter tree based on search text."""
        query = self._search_var.get().lower().strip()
        if not query:
            # Show all items
            for item_id in self._node_map:
                try:
                    # Treeview doesn't have a native show/hide, so we just
                    # detach/reattach. For simplicity, just clear the tag.
                    self._tree.item(item_id, tags=())
                except Exception:
                    pass
            return

        # Apply a visual tag to matching items
        for item_id, node in self._node_map.items():
            info = node.element_info
            searchable = " ".join(
                [
                    info.name,
                    info.automation_id,
                    info.class_name,
                    info.control_type_name,
                    info.path,
                ]
            ).lower()
            if query in searchable:
                self._tree.item(item_id, tags=("match",))
                # Ensure visible
                self._tree.see(item_id)
                parent_id = self._tree.parent(item_id)
                while parent_id:
                    self._tree.item(parent_id, open=True)
                    parent_id = self._tree.parent(parent_id)
            else:
                self._tree.item(item_id, tags=())

        self._tree.tag_configure("match", background="#FFFFCC")

    def _clear_search(self):
        """Clear the search filter."""
        self._search_var.set("")
