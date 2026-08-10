"""
screen_db.py - SQLite-backed screen repository for UIATools.

Stores full UIA tree snapshots (screens) with window-relative element
rectangles, coordinate recordings, and locator choice feedback.

Thread-safety: a single connection is created with check_same_thread=False
and guarded by a lock, since tkinter callbacks and worker threads may both
touch the repository.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.core.tree_walker import TreeNode
from src.core.uia_wrapper import ElementInfo
from src.repository.schema import DDL_STATEMENTS, SCHEMA_VERSION


@dataclass
class ScreenRecord:
    """Metadata for a captured screen."""

    screen_id: int
    label: str
    window_title: str = ""
    process_name: str = ""
    class_name: str = ""
    window_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    max_depth: int = 0
    captured_at: str = ""
    element_count: int = 0


@dataclass
class ElementRecord:
    """A stored element row with reconstructed ElementInfo."""

    element_id: int
    screen_id: int
    path: str
    depth: int
    rect: tuple[int, int, int, int]  # window-relative
    element_info: ElementInfo = field(default_factory=ElementInfo)


@dataclass
class RecordedEvent:
    """A raw recorded input event (click or keystrokes)."""

    seq: int
    t_offset: float
    event_type: str  # "click" | "keys" | "key"
    x: int = 0
    y: int = 0
    button: str = ""
    text: str = ""
    vk_name: str = ""
    redacted: bool = False
    window_title: str = ""
    process_name: str = ""
    window_rect: tuple[int, int, int, int] = (0, 0, 0, 0)


def _parent_path(path: str) -> str:
    """Return the parent path of 'path:1|2|3' -> 'path:1|2'."""
    if not path.startswith("path:"):
        return ""
    parts = path[5:].split("|")
    if len(parts) <= 1:
        return ""
    return "path:" + "|".join(parts[:-1])


def _row_to_element_info(properties_json: str) -> ElementInfo:
    """Reconstruct an ElementInfo from the stored raw-field JSON."""
    info = ElementInfo()
    try:
        raw = json.loads(properties_json)
    except (json.JSONDecodeError, TypeError):
        return info
    for key, value in raw.items():
        if key == "bounding_rect" and isinstance(value, list):
            info.bounding_rect = tuple(value)
        elif hasattr(info, key):
            setattr(info, key, value)
    return info


def _element_info_to_json(info: ElementInfo) -> str:
    """Serialize the raw ElementInfo fields (not the display dict) to JSON."""
    raw = {
        "name": info.name,
        "automation_id": info.automation_id,
        "class_name": info.class_name,
        "control_type": info.control_type,
        "control_type_name": info.control_type_name,
        "localized_control_type": info.localized_control_type,
        "bounding_rect": list(info.bounding_rect),
        "center_x": info.center_x,
        "center_y": info.center_y,
        "is_enabled": info.is_enabled,
        "is_offscreen": info.is_offscreen,
        "is_keyboard_focusable": info.is_keyboard_focusable,
        "has_keyboard_focus": info.has_keyboard_focus,
        "process_id": info.process_id,
        "framework_id": info.framework_id,
        "runtime_id": info.runtime_id,
        "path": info.path,
        "native_window_handle": info.native_window_handle,
        "value": info.value,
        "access_key": info.access_key,
        "accelerator_key": info.accelerator_key,
        "help_text": info.help_text,
        "item_type": info.item_type,
        "item_status": info.item_status,
    }
    return json.dumps(raw, ensure_ascii=False)


class ScreenRepository:
    """
    SQLite-backed repository of screen snapshots and recordings.

    Usage:
        repo = ScreenRepository("myapp_screens.db")
        repo.save_screen(tree_root, "Login Screen", window_meta)
        candidates = repo.find_elements_at(screen_id, rel_x, rel_y)
        repo.close()
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_schema(self):
        with self._lock:
            for ddl in DDL_STATEMENTS:
                self._conn.execute(ddl)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    # ── Screens ───────────────────────────────────────────────

    def save_screen(
        self,
        tree_root: TreeNode,
        label: str,
        window_title: str = "",
        process_name: str = "",
        class_name: str = "",
        window_rect: tuple[int, int, int, int] = (0, 0, 0, 0),
        max_depth: int = 0,
        screenshot: Optional[bytes] = None,
    ) -> int:
        """
        Flatten a TreeNode tree into the repository as a new screen.

        Element rectangles are converted to window-relative coordinates
        using window_rect's top-left corner.

        Returns:
            The new screen_id.
        """
        win_left, win_top = window_rect[0], window_rect[1]
        captured_at = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO screens
                    (label, window_title, process_name, class_name,
                     win_left, win_top, win_right, win_bottom,
                     max_depth, captured_at, screenshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    label, window_title, process_name, class_name,
                    window_rect[0], window_rect[1], window_rect[2], window_rect[3],
                    max_depth, captured_at, screenshot,
                ),
            )
            screen_id = cur.lastrowid

            rows = []
            self._collect_element_rows(tree_root, screen_id, win_left, win_top, rows)
            self._conn.executemany(
                """
                INSERT INTO elements
                    (screen_id, path, parent_path, depth, control_type, name,
                     automation_id, class_name, left, top, right, bottom,
                     center_x, center_y, is_enabled, is_offscreen, properties)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()

        return screen_id

    def _collect_element_rows(
        self,
        node: TreeNode,
        screen_id: int,
        win_left: int,
        win_top: int,
        out_rows: list,
    ):
        """Depth-first flatten of the tree into insert tuples."""
        info = node.element_info
        left, top, right, bottom = info.bounding_rect
        out_rows.append(
            (
                screen_id,
                info.path,
                _parent_path(info.path),
                node.depth,
                info.control_type_name,
                info.name,
                info.automation_id,
                info.class_name,
                left - win_left,
                top - win_top,
                right - win_left,
                bottom - win_top,
                info.center_x - win_left,
                info.center_y - win_top,
                1 if info.is_enabled else 0,
                1 if info.is_offscreen else 0,
                _element_info_to_json(info),
            )
        )
        for child in node.children:
            self._collect_element_rows(child, screen_id, win_left, win_top, out_rows)

    def list_screens(self) -> list[ScreenRecord]:
        """Return metadata for all stored screens."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.*, COUNT(e.element_id) AS element_count
                FROM screens s
                LEFT JOIN elements e ON e.screen_id = s.screen_id
                GROUP BY s.screen_id
                ORDER BY s.captured_at DESC
                """
            ).fetchall()
        return [
            ScreenRecord(
                screen_id=r["screen_id"],
                label=r["label"],
                window_title=r["window_title"],
                process_name=r["process_name"],
                class_name=r["class_name"],
                window_rect=(r["win_left"], r["win_top"], r["win_right"], r["win_bottom"]),
                max_depth=r["max_depth"],
                captured_at=r["captured_at"],
                element_count=r["element_count"],
            )
            for r in rows
        ]

    def get_screen(self, screen_id: int) -> Optional[ScreenRecord]:
        """Return metadata for one screen, or None."""
        with self._lock:
            r = self._conn.execute(
                """
                SELECT s.*, COUNT(e.element_id) AS element_count
                FROM screens s
                LEFT JOIN elements e ON e.screen_id = s.screen_id
                WHERE s.screen_id = ?
                GROUP BY s.screen_id
                """,
                (screen_id,),
            ).fetchone()
        if not r or r["screen_id"] is None:
            return None
        return ScreenRecord(
            screen_id=r["screen_id"],
            label=r["label"],
            window_title=r["window_title"],
            process_name=r["process_name"],
            class_name=r["class_name"],
            window_rect=(r["win_left"], r["win_top"], r["win_right"], r["win_bottom"]),
            max_depth=r["max_depth"],
            captured_at=r["captured_at"],
            element_count=r["element_count"],
        )

    def delete_screen(self, screen_id: int):
        """Delete a screen and all its elements."""
        with self._lock:
            self._conn.execute("DELETE FROM screens WHERE screen_id = ?", (screen_id,))
            self._conn.commit()

    def list_elements(self, screen_id: int) -> list[ElementRecord]:
        """Return all elements of a screen ordered by path depth."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM elements WHERE screen_id = ? ORDER BY element_id",
                (screen_id,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_element(self, element_id: int) -> Optional[ElementRecord]:
        """Return one element row, or None."""
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM elements WHERE element_id = ?", (element_id,)
            ).fetchone()
        return self._row_to_record(r) if r else None

    def _row_to_record(self, r: sqlite3.Row) -> ElementRecord:
        info = _row_to_element_info(r["properties"])
        return ElementRecord(
            element_id=r["element_id"],
            screen_id=r["screen_id"],
            path=r["path"],
            depth=r["depth"],
            rect=(r["left"], r["top"], r["right"], r["bottom"]),
            element_info=info,
        )

    # ── Coordinate lookup (core query) ────────────────────────

    def find_elements_at(
        self, screen_id: int, rel_x: int, rel_y: int, limit: int = 5
    ) -> list[ElementRecord]:
        """
        Find candidate elements whose window-relative rect contains
        (rel_x, rel_y). Deepest and smallest elements first.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM elements
                WHERE screen_id = ?
                  AND ? BETWEEN left AND right
                  AND ? BETWEEN top AND bottom
                  AND is_offscreen = 0
                ORDER BY depth DESC,
                         (right - left) * (bottom - top) ASC
                LIMIT ?
                """,
                (screen_id, rel_x, rel_y, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def match_screen(
        self, window_title: str, process_name: str
    ) -> list[tuple[ScreenRecord, float]]:
        """
        Find stored screens matching a window title + process name.

        Returns list of (screen, score) sorted best-first.
        Exact title+process match scores 1.0; fuzzy title matches
        (same process) score by difflib ratio.
        """
        import difflib

        results: list[tuple[ScreenRecord, float]] = []
        for screen in self.list_screens():
            score = 0.0
            same_process = (
                screen.process_name.lower() == process_name.lower()
                if process_name
                else True
            )
            if not same_process:
                continue
            if screen.window_title == window_title:
                score = 1.0
            elif screen.window_title and window_title:
                score = difflib.SequenceMatcher(
                    None, screen.window_title.lower(), window_title.lower()
                ).ratio()
            if score > 0.5:
                results.append((screen, score))
        results.sort(key=lambda t: t[1], reverse=True)
        return results

    # ── Recordings ────────────────────────────────────────────

    def save_recording(self, label: str, events: list[RecordedEvent]) -> int:
        """Store a coordinate recording. Returns recording_id."""
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO recordings (label, created_at) VALUES (?, ?)",
                (label, created_at),
            )
            recording_id = cur.lastrowid
            self._conn.executemany(
                """
                INSERT INTO recorded_events
                    (recording_id, seq, t_offset, event_type, x, y, button,
                     text, vk_name, redacted, window_title, process_name,
                     win_left, win_top, win_right, win_bottom)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        recording_id, ev.seq, ev.t_offset, ev.event_type,
                        ev.x, ev.y, ev.button, ev.text, ev.vk_name,
                        1 if ev.redacted else 0,
                        ev.window_title, ev.process_name,
                        ev.window_rect[0], ev.window_rect[1],
                        ev.window_rect[2], ev.window_rect[3],
                    )
                    for ev in events
                ],
            )
            self._conn.commit()
        return recording_id

    def list_recordings(self) -> list[dict]:
        """Return [{recording_id, label, created_at, event_count}]."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT r.recording_id, r.label, r.created_at,
                       COUNT(e.event_id) AS event_count
                FROM recordings r
                LEFT JOIN recorded_events e ON e.recording_id = r.recording_id
                GROUP BY r.recording_id
                ORDER BY r.created_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def load_recording(self, recording_id: int) -> list[RecordedEvent]:
        """Load all events of a recording in sequence order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recorded_events WHERE recording_id = ? ORDER BY seq",
                (recording_id,),
            ).fetchall()
        return [
            RecordedEvent(
                seq=r["seq"],
                t_offset=r["t_offset"],
                event_type=r["event_type"],
                x=r["x"],
                y=r["y"],
                button=r["button"],
                text=r["text"],
                vk_name=r["vk_name"],
                redacted=bool(r["redacted"]),
                window_title=r["window_title"],
                process_name=r["process_name"],
                window_rect=(r["win_left"], r["win_top"], r["win_right"], r["win_bottom"]),
            )
            for r in rows
        ]

    def delete_recording(self, recording_id: int):
        """Delete a recording and its events."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM recordings WHERE recording_id = ?", (recording_id,)
            )
            self._conn.commit()

    # ── Locator feedback ──────────────────────────────────────

    def record_chosen_locator(self, element_id: int, locator: str, action: str = ""):
        """Record which locator was finally chosen for an element."""
        chosen_at = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO chosen_locators (element_id, locator, action, chosen_at) "
                "VALUES (?, ?, ?, ?)",
                (element_id, locator, action, chosen_at),
            )
            self._conn.commit()

    def get_preferred_locator(self, element_id: int) -> Optional[str]:
        """Return the most recently chosen locator for an element, if any."""
        with self._lock:
            r = self._conn.execute(
                "SELECT locator FROM chosen_locators WHERE element_id = ? "
                "ORDER BY chosen_at DESC LIMIT 1",
                (element_id,),
            ).fetchone()
        return r["locator"] if r else None
