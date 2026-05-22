"""
recorder.py - Records user interactions (clicks) with element metadata.

Captures each click as a RecordedStep containing:
  - The element info (path, name, automationId, controlType, etc.)
  - The action type (click, right_click, double_click, type_text)
  - Coordinates and timestamp
  - Optional user-supplied text input for Type Text actions

The recorded steps can then be exported to a Robot Framework .robot file
via rf_code_generator.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from src.core.uia_wrapper import ElementInfo


class ActionType(Enum):
    """Types of recordable UI actions."""

    CLICK = "Click"
    RIGHT_CLICK = "Right Click"
    DOUBLE_CLICK = "Double Click"
    TYPE_TEXT = "Type Text"
    SET_VALUE = "Set Value"
    SELECT = "Select"
    GET_ELEMENT = "Get Element"
    WAIT_FOR_ELEMENT = "Wait For Element"
    SEND_KEYS = "Send Keys"  # Send keystrokes to currently focused element


@dataclass
class RecordedStep:
    """A single recorded interaction step."""

    step_number: int
    action: ActionType
    element_info: ElementInfo
    timestamp: float = 0.0
    screen_x: int = 0
    screen_y: int = 0
    text_input: str = ""  # For Type Text / Set Value actions
    locator_override: str = ""  # User can override the auto-chosen locator
    notes: str = ""
    delay_after: float = 0.0  # Seconds to wait after this step
    enabled: bool = True  # Can be toggled off to skip during export
    wait_for_ready: bool = False  # Wait for element to be visible and clickable before action
    wait_after_action: float = 0.0  # Seconds to wait after action completes (for UI to settle)

    @property
    def locator(self) -> str:
        """Return the locator to use: override if set, else best auto locator."""
        if self.locator_override:
            return self.locator_override
        from src.export.locator_strategy import best_locator
        return best_locator(self.element_info)

    @property
    def display_name(self) -> str:
        """Friendly display label for the step list."""
        info = self.element_info
        name = info.name[:30] if info.name else info.automation_id or info.control_type_name
        return f"[{self.step_number}] {self.action.value} → {name}"

    @property
    def rf_keyword(self) -> str:
        """Return the Robot Framework keyword call for this step."""
        locator = self.locator
        if self.action == ActionType.CLICK:
            return f"Click    {locator}"
        elif self.action == ActionType.RIGHT_CLICK:
            return f"Right Click    {locator}"
        elif self.action == ActionType.DOUBLE_CLICK:
            return f"Double Click    {locator}"
        elif self.action == ActionType.TYPE_TEXT:
            return f"Type Text    {locator}    {self.text_input}"
        elif self.action == ActionType.SET_VALUE:
            return f"Set Value    {locator}    {self.text_input}"
        elif self.action == ActionType.SELECT:
            return f"Select    {locator}    {self.text_input}"
        elif self.action == ActionType.GET_ELEMENT:
            return f"${{element}}=    Get Element    {locator}"
        elif self.action == ActionType.WAIT_FOR_ELEMENT:
            return f"Wait For Element    {locator}    timeout=10"
        elif self.action == ActionType.SEND_KEYS:
            # Send Keys doesn't need a locator - sends to focused element
            return f"Send Keys    keys={self.text_input}"
        return f"# Unknown action: {self.action.value}"


class Recorder:
    """
    Records user interactions as a sequence of RecordedSteps.

    Usage:
        recorder = Recorder()
        recorder.start()
        recorder.add_click(x, y, element_info, "left")
        recorder.stop()
        steps = recorder.steps
    """

    def __init__(self):
        self._steps: list[RecordedStep] = []
        self._recording = False
        self._start_time: float = 0.0
        self._on_step_added: Optional[Callable[[RecordedStep], None]] = None
        
        # Default wait settings for new steps
        self.default_wait_for_ready: bool = False
        self.default_wait_after_action: float = 0.0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def steps(self) -> list[RecordedStep]:
        return list(self._steps)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    def set_on_step_added(self, callback: Optional[Callable[[RecordedStep], None]]):
        """Set a callback that fires when a new step is recorded."""
        self._on_step_added = callback

    def start(self):
        """Start recording."""
        self._recording = True
        self._start_time = time.time()

    def stop(self):
        """Stop recording."""
        self._recording = False

    def clear(self):
        """Clear all recorded steps."""
        self._steps.clear()

    def add_click(
        self,
        x: int,
        y: int,
        element_info: ElementInfo,
        button: str = "left",
    ) -> RecordedStep:
        """
        Record a click action.

        Args:
            x, y: Screen coordinates of the click.
            element_info: The UIA element info at the click point.
            button: "left" or "right".

        Returns:
            The recorded step.
        """
        if not self._recording:
            return None

        action = ActionType.RIGHT_CLICK if button == "right" else ActionType.CLICK
        step_num = len(self._steps) + 1

        step = RecordedStep(
            step_number=step_num,
            action=action,
            element_info=element_info,
            timestamp=time.time() - self._start_time,
            screen_x=x,
            screen_y=y,
            wait_for_ready=self.default_wait_for_ready,
            wait_after_action=self.default_wait_after_action,
        )
        self._steps.append(step)

        if self._on_step_added:
            try:
                self._on_step_added(step)
            except Exception:
                pass

        return step

    def add_manual_step(
        self,
        action: ActionType,
        element_info: ElementInfo,
        text_input: str = "",
    ) -> RecordedStep:
        """Add a manual step (e.g., Type Text added after a click)."""
        step_num = len(self._steps) + 1
        step = RecordedStep(
            step_number=step_num,
            action=action,
            element_info=element_info,
            timestamp=time.time() - self._start_time if self._recording else 0,
            screen_x=element_info.center_x,
            screen_y=element_info.center_y,
            text_input=text_input,
            wait_for_ready=self.default_wait_for_ready,
            wait_after_action=self.default_wait_after_action,
        )
        self._steps.append(step)

        if self._on_step_added:
            try:
                self._on_step_added(step)
            except Exception:
                pass

        return step

    def insert_step_after(self, index: int, step: RecordedStep):
        """Insert a step after the given index."""
        self._steps.insert(index + 1, step)
        self._renumber()

    def remove_step(self, index: int):
        """Remove a step by index."""
        if 0 <= index < len(self._steps):
            self._steps.pop(index)
            self._renumber()

    def move_step_up(self, index: int):
        """Move a step up by one position."""
        if index > 0:
            self._steps[index - 1], self._steps[index] = (
                self._steps[index],
                self._steps[index - 1],
            )
            self._renumber()

    def move_step_down(self, index: int):
        """Move a step down by one position."""
        if index < len(self._steps) - 1:
            self._steps[index], self._steps[index + 1] = (
                self._steps[index + 1],
                self._steps[index],
            )
            self._renumber()

    def update_step_action(self, index: int, action: ActionType):
        """Change the action type of a step."""
        if 0 <= index < len(self._steps):
            self._steps[index].action = action

    def update_step_text(self, index: int, text: str):
        """Update the text_input of a step."""
        if 0 <= index < len(self._steps):
            self._steps[index].text_input = text

    def update_step_locator(self, index: int, locator: str):
        """Override the locator for a step."""
        if 0 <= index < len(self._steps):
            self._steps[index].locator_override = locator

    def update_step_wait_settings(
        self,
        index: int,
        wait_for_ready: bool = None,
        wait_after_action: float = None,
    ):
        """Update wait settings for a step."""
        if 0 <= index < len(self._steps):
            if wait_for_ready is not None:
                self._steps[index].wait_for_ready = wait_for_ready
            if wait_after_action is not None:
                self._steps[index].wait_after_action = wait_after_action

    def set_all_steps_wait(self, wait_for_ready: bool = None, wait_after_action: float = None):
        """Set wait settings for all recorded steps."""
        for step in self._steps:
            if wait_for_ready is not None:
                step.wait_for_ready = wait_for_ready
            if wait_after_action is not None:
                step.wait_after_action = wait_after_action

    def _renumber(self):
        """Re-assign step numbers sequentially."""
        for i, step in enumerate(self._steps, start=1):
            step.step_number = i
