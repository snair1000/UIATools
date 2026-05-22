"""
rf_code_generator.py - Generates complete Robot Framework .robot files
from recorded interaction steps.

Produces:
  - *** Settings *** section with Library import
  - *** Variables *** section with locator variables
  - *** Tasks *** section with the recorded keyword calls
  - *** Keywords *** section with a reusable keyword wrapping the steps

The generated code uses RPA.Windows library syntax and follows
Robot Framework best practices for maintainability.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from src.core.recorder import ActionType, RecordedStep
from src.export.locator_strategy import best_locator, build_locator_strategies


def generate_robot_file(
    steps: list[RecordedStep],
    task_name: str = "Recorded Interaction",
    window_locator: str = "",
    include_comments: bool = True,
    use_variables: bool = True,
    include_delays: bool = False,
    include_keyword: bool = True,
) -> str:
    """
    Generate a complete .robot file from recorded steps.

    Args:
        steps: The list of RecordedStep objects.
        task_name: Name of the generated Task.
        window_locator: If set, adds a Control Window call at the top.
        include_comments: Add comments with element details.
        use_variables: Create locator variables in *** Variables *** section.
        include_delays: Include Sleep calls between steps.
        include_keyword: Also generate a reusable keyword.

    Returns:
        The complete .robot file content as a string.
    """
    lines: list[str] = []

    # *** Settings ***
    lines.append("*** Settings ***")
    lines.append("Library    RPA.Windows")
    lines.append("")

    # Build locator variables (deduplicated)
    var_map: dict[str, str] = {}  # variable_name -> locator
    if use_variables:
        for step in steps:
            if not step.enabled:
                continue
            var_name = _make_variable_name(step)
            locator = step.locator
            if var_name not in var_map:
                var_map[var_name] = locator

    # *** Variables ***
    if var_map:
        lines.append("*** Variables ***")
        for var_name, locator in var_map.items():
            lines.append(f"${{{var_name}}}    {locator}")
            if include_comments:
                info = _find_step_for_var(steps, var_name)
                if info:
                    lines.append(f"# {info.element_info.control_type_name}: "
                                 f"Name='{info.element_info.name}', "
                                 f"AutomationId='{info.element_info.automation_id}'")
        lines.append("")

    # *** Tasks ***
    lines.append("*** Tasks ***")
    lines.append(task_name)

    if window_locator:
        lines.append(f"    Control Window    {window_locator}")
        lines.append("")

    if include_keyword:
        # Task calls the keyword
        keyword_name = _sanitize_keyword_name(task_name)
        lines.append(f"    {keyword_name}")
    else:
        # Inline all steps in the task
        _append_steps(lines, steps, var_map, use_variables, include_comments, include_delays)

    lines.append("")

    # *** Keywords ***
    if include_keyword:
        keyword_name = _sanitize_keyword_name(task_name)
        lines.append("*** Keywords ***")
        lines.append(keyword_name)
        if include_comments:
            lines.append(f"    [Documentation]    Auto-recorded interaction "
                         f"({len([s for s in steps if s.enabled])} steps)")
        _append_steps(lines, steps, var_map, use_variables, include_comments, include_delays)
        lines.append("")

    return "\n".join(lines)


def generate_keyword_only(
    steps: list[RecordedStep],
    keyword_name: str = "Recorded Interaction",
    use_variables: bool = False,
    include_comments: bool = True,
) -> str:
    """
    Generate just a *** Keywords *** block (for pasting into existing files).
    """
    lines: list[str] = []
    var_map: dict[str, str] = {}

    if use_variables:
        for step in steps:
            if step.enabled:
                var_name = _make_variable_name(step)
                if var_name not in var_map:
                    var_map[var_name] = step.locator

    lines.append(keyword_name)
    if include_comments:
        lines.append(f"    [Documentation]    Auto-recorded interaction "
                     f"({len([s for s in steps if s.enabled])} steps)")
    _append_steps(lines, steps, var_map, use_variables, include_comments, False)
    return "\n".join(lines)


def generate_variables_section(steps: list[RecordedStep]) -> str:
    """Generate just the *** Variables *** section."""
    lines = ["*** Variables ***"]
    seen: set[str] = set()
    for step in steps:
        if not step.enabled:
            continue
        var_name = _make_variable_name(step)
        if var_name not in seen:
            seen.add(var_name)
            lines.append(f"${{{var_name}}}    {step.locator}")
    return "\n".join(lines)


# ── Internal Helpers ─────────────────────────────────────────


def _append_steps(
    lines: list[str],
    steps: list[RecordedStep],
    var_map: dict[str, str],
    use_variables: bool,
    include_comments: bool,
    include_delays: bool,
):
    """Append step keyword calls to lines."""
    prev_timestamp = 0.0

    for step in steps:
        if not step.enabled:
            if include_comments:
                lines.append(f"    # SKIPPED: Step {step.step_number} - {step.action.value}")
            continue

        # Optional delay
        if include_delays and step.timestamp > 0:
            delay = step.timestamp - prev_timestamp
            if delay > 0.5:
                lines.append(f"    Sleep    {delay:.1f}s")
            prev_timestamp = step.timestamp

        # Comment with element details
        if include_comments:
            info = step.element_info
            comment_parts = []
            if info.name:
                comment_parts.append(f"Name='{info.name[:40]}'")
            if info.automation_id:
                comment_parts.append(f"Id='{info.automation_id}'")
            comment_parts.append(f"Type={info.control_type_name}")
            comment_parts.append(f"Path={info.path}")
            lines.append(f"    # Step {step.step_number}: {', '.join(comment_parts)}")

        # Build the locator reference
        if use_variables and var_map:
            var_name = _make_variable_name(step)
            locator_ref = f"${{{var_name}}}"
        else:
            locator_ref = step.locator

        # Build the keyword line
        action = step.action
        if action == ActionType.CLICK:
            lines.append(f"    Click    {locator_ref}")
        elif action == ActionType.RIGHT_CLICK:
            lines.append(f"    Right Click    {locator_ref}")
        elif action == ActionType.DOUBLE_CLICK:
            lines.append(f"    Double Click    {locator_ref}")
        elif action == ActionType.TYPE_TEXT:
            text = step.text_input or "ENTER_TEXT_HERE"
            lines.append(f"    Click    {locator_ref}")
            lines.append(f"    Type Text    {locator_ref}    {text}")
        elif action == ActionType.SET_VALUE:
            text = step.text_input or "ENTER_VALUE_HERE"
            lines.append(f"    Set Value    {locator_ref}    {text}")
        elif action == ActionType.SELECT:
            text = step.text_input or "ENTER_OPTION_HERE"
            lines.append(f"    Select    {locator_ref}    {text}")
        elif action == ActionType.GET_ELEMENT:
            safe_name = _safe_var_suffix(step)
            lines.append(f"    ${{elem_{safe_name}}}=    Get Element    {locator_ref}")
        elif action == ActionType.WAIT_FOR_ELEMENT:
            lines.append(f"    Wait For Element    {locator_ref}    timeout=10")
        else:
            lines.append(f"    # Unknown action: {action.value} on {locator_ref}")

        # Custom delay after step
        if step.delay_after > 0:
            lines.append(f"    Sleep    {step.delay_after:.1f}s")

        # Notes
        if step.notes and include_comments:
            lines.append(f"    # Note: {step.notes}")


def _make_variable_name(step: RecordedStep) -> str:
    """Create a meaningful variable name for the step's locator."""
    info = step.element_info
    parts = ["LOCATOR"]

    # Add control type
    if info.control_type_name:
        type_short = info.control_type_name.replace("Control", "").upper()
        if type_short:
            parts.append(type_short)

    # Add name or automationid
    if info.automation_id:
        parts.append(_sanitize(info.automation_id).upper())
    elif info.name:
        name_clean = _sanitize(info.name[:20]).upper()
        if name_clean:
            parts.append(name_clean)
    else:
        parts.append(f"STEP_{step.step_number}")

    return "_".join(parts)


def _sanitize(text: str) -> str:
    """Sanitize text for use in variable names."""
    # Replace non-alphanumeric with underscore
    result = re.sub(r"[^a-zA-Z0-9]", "_", text)
    # Collapse multiple underscores
    result = re.sub(r"_+", "_", result)
    # Strip leading/trailing underscores
    return result.strip("_")


def _sanitize_keyword_name(name: str) -> str:
    """Sanitize text for use as a keyword name."""
    result = re.sub(r"[^a-zA-Z0-9 _-]", "", name)
    return result.strip() or "Recorded Interaction"


def _safe_var_suffix(step: RecordedStep) -> str:
    """Create a safe variable suffix from element info."""
    info = step.element_info
    if info.automation_id:
        return _sanitize(info.automation_id).lower()
    if info.name:
        return _sanitize(info.name[:15]).lower()
    return f"step_{step.step_number}"


def _find_step_for_var(steps: list[RecordedStep], var_name: str) -> Optional[RecordedStep]:
    """Find the first step matching a variable name."""
    for step in steps:
        if step.enabled and _make_variable_name(step) == var_name:
            return step
    return None
