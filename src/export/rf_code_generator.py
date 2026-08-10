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

    # Steps may carry their own window context (AI generation); in that case
    # per-step Control Window transitions are emitted instead of one top call.
    steps_have_windows = any(s.enabled and s.window_locator for s in steps)

    win_var_map = _build_window_var_map(steps, "" if steps_have_windows else window_locator)
    anchor_var_map = _build_anchor_var_map(steps)
    value_var_map = _build_value_var_map(steps) if use_variables else {}

    # Build locator variables (deduplicated)
    var_map: dict[str, str] = {}  # variable_name -> locator
    if use_variables:
        for step in steps:
            if not step.enabled:
                continue
            locator = step.locator
            if not locator.strip():
                continue  # e.g. Send Keys steps have no locator
            var_name = _make_variable_name(step)
            if var_name not in var_map:
                var_map[var_name] = locator

    # *** Variables ***
    if var_map or win_var_map or anchor_var_map or value_var_map:
        lines.append("*** Variables ***")
        # Windows first - all controls below belong to one of these windows
        if use_variables and win_var_map:
            for locator, var_name in win_var_map.items():
                lines.append(f"${{{var_name}}}    {locator}")
        # WebView2 / panel anchors
        if use_variables and anchor_var_map:
            for locator, var_name in anchor_var_map.items():
                lines.append(f"${{{var_name}}}    {locator}")
        # Element locators, grouped per window for easy maintenance
        if use_variables and steps_have_windows and len(win_var_map) > 0:
            emitted: set[str] = set()
            for win_locator, win_var in win_var_map.items():
                group = [
                    (v, l) for v, l in var_map.items()
                    if v not in emitted and _var_belongs_to_window(steps, v, win_locator)
                ]
                if not group:
                    continue
                lines.append(f"# --- Controls in window: ${{{win_var}}} ---")
                for var_name, locator in group:
                    emitted.add(var_name)
                    lines.append(f"${{{var_name}}}    {locator}")
                    if include_comments:
                        info = _find_step_for_var(steps, var_name)
                        if info:
                            lines.append(f"# {info.element_info.control_type_name}: "
                                         f"Name='{info.element_info.name}', "
                                         f"AutomationId='{info.element_info.automation_id}'")
            # Any leftovers (steps without window context)
            for var_name, locator in var_map.items():
                if var_name not in emitted:
                    lines.append(f"${{{var_name}}}    {locator}")
        else:
            for var_name, locator in var_map.items():
                lines.append(f"${{{var_name}}}    {locator}")
                if include_comments:
                    info = _find_step_for_var(steps, var_name)
                    if info:
                        lines.append(f"# {info.element_info.control_type_name}: "
                                     f"Name='{info.element_info.name}', "
                                     f"AutomationId='{info.element_info.automation_id}'")
        # Typed values
        if use_variables and value_var_map:
            for var_name, text in value_var_map.items():
                lines.append(f"${{{var_name}}}    {text}")
        lines.append("")

    if not use_variables:
        win_var_map = {}
        anchor_var_map = {}
        value_var_map = {}

    # *** Tasks ***
    lines.append("*** Tasks ***")
    lines.append(task_name)

    if window_locator and not steps_have_windows:
        lines.append(f"    Control Window    {_ref_for(window_locator, win_var_map)}")
        lines.append("")

    if include_keyword:
        # Task calls the keyword
        keyword_name = _sanitize_keyword_name(task_name)
        lines.append(f"    {keyword_name}")
    else:
        # Inline all steps in the task
        _append_steps(lines, steps, var_map, use_variables, include_comments,
                      include_delays, win_var_map, anchor_var_map, value_var_map)

    lines.append("")

    # *** Keywords ***
    if include_keyword:
        keyword_name = _sanitize_keyword_name(task_name)
        lines.append("*** Keywords ***")
        lines.append(keyword_name)
        if include_comments:
            lines.append(f"    [Documentation]    Auto-recorded interaction "
                         f"({len([s for s in steps if s.enabled])} steps)")
        _append_steps(lines, steps, var_map, use_variables, include_comments,
                      include_delays, win_var_map, anchor_var_map, value_var_map)
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
    win_var_map: Optional[dict[str, str]] = None,
    anchor_var_map: Optional[dict[str, str]] = None,
    value_var_map: Optional[dict[str, str]] = None,
):
    """Append step keyword calls to lines."""
    win_var_map = win_var_map or {}
    anchor_var_map = anchor_var_map or {}
    value_var_map = value_var_map or {}
    prev_timestamp = 0.0
    current_window = ""
    current_anchors: list[str] = []

    for step in steps:
        if not step.enabled:
            if include_comments:
                lines.append(f"    # SKIPPED: Step {step.step_number} - {step.action.value}")
            continue

        # Window transition: focus follows the recorded foreground window
        if step.window_locator and step.window_locator != current_window:
            lines.append(f"    Control Window    {_ref_for(step.window_locator, win_var_map)}")
            current_window = step.window_locator
            current_anchors = []

        # Anchor transition (WebView2 host panel, then inner panel)
        anchors = list(step.anchor_locators)
        if anchors != current_anchors:
            if current_anchors and current_anchors != anchors[: len(current_anchors)]:
                # New chain is not an extension - reset scope to the window
                if current_window:
                    lines.append(
                        f"    Control Window    {_ref_for(current_window, win_var_map)}"
                    )
                start = 0
            else:
                start = len(current_anchors)
            for anchor in anchors[start:]:
                lines.append(f"    Set Anchor    {_ref_for(anchor, anchor_var_map)}")
            current_anchors = anchors

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
            timeout = step.wait_timeout if step.wait_timeout > 0 else 10
            lines.append(f"    Wait For Element    {locator_ref}    timeout={timeout}")
        elif action == ActionType.SEND_KEYS:
            keys = step.text_input or "ENTER_KEYS_HERE"
            if step.locator.strip():
                # Typed value targeted at a specific element
                value_ref = _value_ref_for(step, value_var_map)
                lines.append(f"    Send Keys    {locator_ref}    {value_ref}")
            else:
                # Special keys / no target - send to the focused element
                lines.append(f"    Send Keys    keys={keys}")
        else:
            lines.append(f"    # Unknown action: {action.value} on {locator_ref}")

        # Custom delay after step
        if step.delay_after > 0:
            lines.append(f"    Sleep    {step.delay_after:.1f}s")

        # Notes
        if step.notes and include_comments:
            lines.append(f"    # Note: {step.notes}")


def _ref_for(locator: str, var_map: dict[str, str]) -> str:
    """Return the ${VAR} reference for a locator, or the locator itself."""
    var_name = var_map.get(locator)
    return f"${{{var_name}}}" if var_name else locator


def _build_window_var_map(
    steps: list[RecordedStep], top_window_locator: str = ""
) -> dict[str, str]:
    """Map each distinct window locator to a ${WIN_*} variable name."""
    result: dict[str, str] = {}
    ordered = []
    if top_window_locator:
        ordered.append(top_window_locator)
    for step in steps:
        if step.enabled and step.window_locator:
            ordered.append(step.window_locator)
    for locator in ordered:
        if locator in result:
            continue
        suffix = _sanitize(locator.split(":", 1)[-1][:24]).upper()
        name = f"WIN_{suffix}" if suffix else f"WIN_{len(result) + 1}"
        # Ensure uniqueness
        base, n = name, 2
        while name in result.values():
            name = f"{base}_{n}"
            n += 1
        result[locator] = name
    return result


def _build_anchor_var_map(steps: list[RecordedStep]) -> dict[str, str]:
    """Map each distinct anchor locator to an ${ANCHOR_*} variable name."""
    result: dict[str, str] = {}
    for step in steps:
        if not step.enabled:
            continue
        for locator in step.anchor_locators:
            if not locator or locator in result:
                continue
            suffix = _sanitize(locator.split(":", 1)[-1][:24]).upper()
            name = f"ANCHOR_{suffix}" if suffix else f"ANCHOR_{len(result) + 1}"
            base, n = name, 2
            while name in result.values():
                name = f"{base}_{n}"
                n += 1
            result[locator] = name
    return result


def _build_value_var_map(steps: list[RecordedStep]) -> dict[str, str]:
    """
    Map typed values (Send Keys into a specific element) to ${VALUE_*}
    variables: variable_name -> text value.
    """
    result: dict[str, str] = {}
    for step in steps:
        if not step.enabled or step.action != ActionType.SEND_KEYS:
            continue
        if not step.locator.strip() or not step.text_input:
            continue
        suffix = _safe_var_suffix(step).upper()
        name = f"VALUE_{suffix}"
        base, n = name, 2
        while name in result and result[name] != step.text_input:
            name = f"{base}_{n}"
            n += 1
        result[name] = step.text_input
    return result


def _value_ref_for(step: RecordedStep, value_var_map: dict[str, str]) -> str:
    """Return the ${VALUE_*} reference for a step's typed text, or the text."""
    for name, text in value_var_map.items():
        if text == step.text_input:
            return f"${{{name}}}"
    return step.text_input or "ENTER_KEYS_HERE"


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


def _var_belongs_to_window(
    steps: list[RecordedStep], var_name: str, window_locator: str
) -> bool:
    """True if the first step using this variable belongs to the window."""
    for step in steps:
        if step.enabled and _make_variable_name(step) == var_name:
            return step.window_locator == window_locator
    return False


def _find_step_for_var(steps: list[RecordedStep], var_name: str) -> Optional[RecordedStep]:
    """Find the first step matching a variable name."""
    for step in steps:
        if step.enabled and _make_variable_name(step) == var_name:
            return step
    return None
