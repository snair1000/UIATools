"""
schema.py - SQLite schema definitions for the UIATools screen repository.

The repository stores full UIA tree snapshots ("screens") with all element
properties and window-relative bounding rectangles, plus lightweight
coordinate recordings and a locator feedback table.

All element rectangles are stored WINDOW-RELATIVE (the captured window's
top-left corner is 0,0) so that recorded clicks can be resolved even when
the window has moved between capture and recording.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screens (
        screen_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        label        TEXT NOT NULL,
        window_title TEXT DEFAULT '',
        process_name TEXT DEFAULT '',
        class_name   TEXT DEFAULT '',
        win_left     INTEGER DEFAULT 0,
        win_top      INTEGER DEFAULT 0,
        win_right    INTEGER DEFAULT 0,
        win_bottom   INTEGER DEFAULT 0,
        max_depth    INTEGER DEFAULT 0,
        captured_at  TEXT DEFAULT '',
        screenshot   BLOB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS elements (
        element_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        screen_id     INTEGER NOT NULL REFERENCES screens(screen_id) ON DELETE CASCADE,
        path          TEXT NOT NULL,
        parent_path   TEXT DEFAULT '',
        depth         INTEGER DEFAULT 0,
        control_type  TEXT DEFAULT '',
        name          TEXT DEFAULT '',
        automation_id TEXT DEFAULT '',
        class_name    TEXT DEFAULT '',
        left          INTEGER DEFAULT 0,
        top           INTEGER DEFAULT 0,
        right         INTEGER DEFAULT 0,
        bottom        INTEGER DEFAULT 0,
        center_x      INTEGER DEFAULT 0,
        center_y      INTEGER DEFAULT 0,
        is_enabled    INTEGER DEFAULT 0,
        is_offscreen  INTEGER DEFAULT 0,
        properties    TEXT DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_elements_rect
        ON elements(screen_id, left, top, right, bottom)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_elements_path
        ON elements(screen_id, path)
    """,
    """
    CREATE TABLE IF NOT EXISTS recordings (
        recording_id INTEGER PRIMARY KEY AUTOINCREMENT,
        label        TEXT NOT NULL,
        created_at   TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recorded_events (
        event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
        seq          INTEGER NOT NULL,
        t_offset     REAL DEFAULT 0.0,
        event_type   TEXT NOT NULL,
        x            INTEGER DEFAULT 0,
        y            INTEGER DEFAULT 0,
        button       TEXT DEFAULT '',
        text         TEXT DEFAULT '',
        vk_name      TEXT DEFAULT '',
        redacted     INTEGER DEFAULT 0,
        window_title TEXT DEFAULT '',
        process_name TEXT DEFAULT '',
        win_left     INTEGER DEFAULT 0,
        win_top      INTEGER DEFAULT 0,
        win_right    INTEGER DEFAULT 0,
        win_bottom   INTEGER DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_recording
        ON recorded_events(recording_id, seq)
    """,
    """
    CREATE TABLE IF NOT EXISTS chosen_locators (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        element_id INTEGER NOT NULL REFERENCES elements(element_id) ON DELETE CASCADE,
        locator    TEXT NOT NULL,
        action     TEXT DEFAULT '',
        chosen_at  TEXT DEFAULT ''
    )
    """,
]
