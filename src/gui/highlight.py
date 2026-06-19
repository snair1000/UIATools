"""
highlight.py - Element highlight overlay.

Creates a transparent overlay window that draws a colored rectangle
around a UIA element to visually indicate which element is selected.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class HighlightOverlay:
    """
    A transparent, click-through overlay window that highlights a
    rectangular area on screen (e.g., a UIA element's bounding rectangle).
    """

    def __init__(self, color: str = "red", border_width: int = 3):
        self._color = color
        self._border_width = border_width
        self._overlay: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None

    def show(self, left: int, top: int, right: int, bottom: int):
        """
        Show the highlight overlay around the given rectangle.

        Args:
            left, top, right, bottom: Screen coordinates of the bounding rect.
        """
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            self.hide()
            return

        if self._overlay is None:
            self._create_overlay()

        self._overlay.geometry(f"{width}x{height}+{left}+{top}")

        # Draw the border rectangle
        self._canvas.delete("all")
        self._canvas.config(width=width, height=height)
        bw = self._border_width
        # Draw 4 rectangles to form a border (since the interior should be transparent)
        # Top edge
        self._canvas.create_rectangle(0, 0, width, bw, fill=self._color, outline="")
        # Bottom edge
        self._canvas.create_rectangle(0, height - bw, width, height, fill=self._color, outline="")
        # Left edge
        self._canvas.create_rectangle(0, bw, bw, height - bw, fill=self._color, outline="")
        # Right edge
        self._canvas.create_rectangle(width - bw, bw, width, height - bw, fill=self._color, outline="")

        self._overlay.deiconify()
        self._overlay.lift()
        self._overlay.update()

    def hide(self):
        """Hide the highlight overlay."""
        if self._overlay:
            self._overlay.withdraw()

    def destroy(self):
        """Destroy the overlay window."""
        if self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None
            self._canvas = None

    def _create_overlay(self):
        """Create the transparent overlay window."""
        self._overlay = tk.Toplevel()
        self._overlay.overrideredirect(True)
        self._overlay.attributes("-topmost", True)

        # Make the window transparent - use a color key for transparency
        transparent_color = "#010101"  # Near-black that we'll make transparent
        self._overlay.attributes("-transparentcolor", transparent_color)
        self._overlay.config(bg=transparent_color)

        self._canvas = tk.Canvas(
            self._overlay,
            bg=transparent_color,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Start hidden
        self._overlay.withdraw()

    def set_color(self, color: str):
        """Change the highlight color."""
        self._color = color
