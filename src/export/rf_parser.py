"""
rf_parser.py - Parses Robot Framework .robot files back into RecordedSteps.

Allows loading previously saved .robot files into UIATools for:
  - Viewing the recorded steps
  - Editing and modifying the automation
  - Re-running the automation within the tool
  - Exporting with different options

Supports:
  - Parsing action keywords (Click, Type Text, etc.)
  - Extracting locators from keyword calls
  - Resolving variable references (${LOCATOR_NAME})
  - Handling both Tasks and Keywords sections
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.core.recorder import ActionType, RecordedStep
from src.core.uia_wrapper import ElementInfo


@dataclass
class ParseResult:
    """Result of parsing a .robot file."""
    steps: list[RecordedStep]
    task_name: str
    window_locator: str
    variables: dict[str, str]
    errors: list[str]
    warnings: list[str]


# Mapping from RF keyword names to ActionType
KEYWORD_ACTION_MAP = {
    "click": ActionType.CLICK,
    "right click": ActionType.RIGHT_CLICK,
    "rightclick": ActionType.RIGHT_CLICK,
    "double click": ActionType.DOUBLE_CLICK,
    "doubleclick": ActionType.DOUBLE_CLICK,
    "type text": ActionType.TYPE_TEXT,
    "typetext": ActionType.TYPE_TEXT,
    "set value": ActionType.SET_VALUE,
    "setvalue": ActionType.SET_VALUE,
    "select": ActionType.SELECT,
    "get element": ActionType.GET_ELEMENT,
    "getelement": ActionType.GET_ELEMENT,
    "wait for element": ActionType.WAIT_FOR_ELEMENT,
    "waitforelement": ActionType.WAIT_FOR_ELEMENT,
    "send keys": ActionType.SEND_KEYS,
    "sendkeys": ActionType.SEND_KEYS,
}

# Keywords that take a second text argument
TEXT_KEYWORDS = {
    ActionType.TYPE_TEXT,
    ActionType.SET_VALUE,
    ActionType.SELECT,
    ActionType.SEND_KEYS,
}


def parse_robot_file(filepath: str) -> ParseResult:
    """
    Parse a .robot file and extract steps.

    Args:
        filepath: Path to the .robot file.

    Returns:
        ParseResult containing steps, metadata, and any errors/warnings.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return ParseResult(
            steps=[],
            task_name="",
            window_locator="",
            variables={},
            errors=[f"Failed to read file: {e}"],
            warnings=[],
        )

    return parse_robot_content(content)


def parse_robot_content(content: str) -> ParseResult:
    """
    Parse Robot Framework content string and extract steps.

    Args:
        content: The .robot file content as a string.

    Returns:
        ParseResult containing steps, metadata, and any errors/warnings.
    """
    lines = content.split("\n")
    
    variables: dict[str, str] = {}
    steps: list[RecordedStep] = []
    errors: list[str] = []
    warnings: list[str] = []
    task_name = ""
    window_locator = ""
    
    current_section = None
    step_number = 0
    
    for line_num, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()
        
        # Skip empty lines and comments
        if not line or line.strip().startswith("#"):
            continue
        
        # Detect section headers
        if line.startswith("***"):
            section_match = re.match(r"\*\*\*\s*(\w+)", line, re.IGNORECASE)
            if section_match:
                section_name = section_match.group(1).lower()
                if section_name in ("settings", "setting"):
                    current_section = "settings"
                elif section_name in ("variables", "variable"):
                    current_section = "variables"
                elif section_name in ("tasks", "task", "test cases", "test case", "testcases"):
                    current_section = "tasks"
                elif section_name in ("keywords", "keyword"):
                    current_section = "keywords"
                else:
                    current_section = section_name
            continue
        
        # Parse based on current section
        if current_section == "variables":
            var_match = re.match(r"\$\{([^}]+)\}\s+(.+)", line.strip())
            if var_match:
                var_name = var_match.group(1)
                var_value = var_match.group(2).strip()
                variables[var_name] = var_value
        
        elif current_section == "tasks":
            # Task name (non-indented line that's not a keyword)
            if not line.startswith((" ", "\t")):
                task_name = line.strip()
                continue
            
            # Control Window call - capture the window locator (used to scope playback)
            stripped = line.strip()
            if stripped.lower().startswith("control window"):
                rest = stripped[len("control window"):].strip()
                if rest and not window_locator:
                    window_locator = _resolve_variable(
                        re.split(r"\s{2,}", rest)[0].strip(), variables
                    )
                continue
            
            # Set Anchor - scoping hint for RPA.Windows, not an executable step
            if stripped.lower().startswith("set anchor"):
                continue
            
            # Sleep -> record as delay after the previous step
            if stripped.lower().startswith("sleep") and steps:
                delay = _parse_sleep_duration(stripped)
                if delay > 0:
                    steps[-1].wait_after_action = delay
                continue
            
            # Keyword call (indented)
            step = _parse_keyword_line(line, variables, step_number + 1, line_num)
            if step:
                step_number += 1
                steps.append(step)
        
        elif current_section == "keywords":
            # Skip keyword definitions (non-indented) and [Documentation] etc.
            if not line.startswith((" ", "\t")):
                continue
            if re.match(r"\s*\[", line):  # [Documentation], [Arguments], etc.
                continue
            
            stripped = line.strip()
            # Control Window inside keyword body - capture first for scoping
            if stripped.lower().startswith("control window"):
                rest = stripped[len("control window"):].strip()
                if rest and not window_locator:
                    window_locator = _resolve_variable(
                        re.split(r"\s{2,}", rest)[0].strip(), variables
                    )
                continue
            
            # Set Anchor - scoping hint, not an executable step
            if stripped.lower().startswith("set anchor"):
                continue
            
            # Sleep -> record as delay after the previous step
            if stripped.lower().startswith("sleep") and steps:
                delay = _parse_sleep_duration(stripped)
                if delay > 0:
                    steps[-1].wait_after_action = delay
                continue
            
            step = _parse_keyword_line(line, variables, step_number + 1, line_num)
            if step:
                step_number += 1
                steps.append(step)
    
    return ParseResult(
        steps=steps,
        task_name=task_name,
        window_locator=window_locator,
        variables=variables,
        errors=errors,
        warnings=warnings,
    )


def _parse_keyword_line(
    line: str,
    variables: dict[str, str],
    step_number: int,
    line_num: int,
) -> Optional[RecordedStep]:
    """
    Parse a single keyword line into a RecordedStep.

    Args:
        line: The line content (should be indented keyword call).
        variables: Dictionary of variable names to values.
        step_number: The step number to assign.
        line_num: Line number in the file (for error reporting).

    Returns:
        RecordedStep if line is a recognized action keyword, None otherwise.
    """
    line = line.strip()
    
    # Skip empty, comments, Sleep, Log, etc.
    if not line or line.startswith("#"):
        return None
    
    lower_line = line.lower()
    
    # Skip non-action keywords. Note: must not swallow "Set Value" -
    # only skip specific RF built-in "Set ..." keywords.
    skip_prefixes = (
        "sleep", "log", "should", "wait until", "run keyword", "return", "[",
        "set global", "set suite", "set test", "set task", "set local", "set variable",
    )
    if any(lower_line.startswith(p) for p in skip_prefixes):
        return None
    
    # Handle "Control Window" specially - not a step we execute
    if lower_line.startswith("control window"):
        return None
    
    # Try to parse as action keyword
    action_type = None
    locator = ""
    text_input = ""
    
    # Handle variable assignment: ${var}=    Get Element    locator
    assignment_match = re.match(r"\$\{[^}]+\}\s*=\s*", line)
    if assignment_match:
        line = line[assignment_match.end():].strip()
        lower_line = line.lower()
    
    # Try to match multi-word keywords first
    # Sort keywords by length (longest first) to match "Type Text" before "Type"
    sorted_keywords = sorted(KEYWORD_ACTION_MAP.keys(), key=len, reverse=True)
    
    matched_keyword = None
    for kw_name in sorted_keywords:
        # Check if line starts with this keyword (case-insensitive)
        if lower_line.startswith(kw_name):
            # Make sure it's followed by whitespace or end of line
            rest = line[len(kw_name):]
            if not rest or rest[0] in (' ', '\t'):
                action_type = KEYWORD_ACTION_MAP[kw_name]
                matched_keyword = kw_name
                line = rest.strip()
                break
    
    if action_type is None:
        return None
    
    # Now split the remaining arguments by 2+ spaces
    if line:
        parts = re.split(r"\s{2,}", line)
    else:
        parts = []
    
    # Extract locator (first argument)
    if parts:
        locator = parts[0].strip()
        locator = _resolve_variable(locator, variables)
    
    # Extract text input for keywords that need it
    if action_type in TEXT_KEYWORDS:
        if action_type == ActionType.SEND_KEYS:
            # Forms:
            #   Send Keys    keys={TAB}                (focused element)
            #   Send Keys    ${LOCATOR}    ${VALUE}    (typed into element)
            keys_arg = ""
            positional = []
            for part in parts:
                part = part.strip()
                if part.lower().startswith("keys="):
                    keys_arg = part[5:]
                else:
                    positional.append(part)
            if keys_arg:
                text_input = _resolve_variable(keys_arg, variables)
                locator = (
                    _resolve_variable(positional[0], variables)
                    if positional else "(focused element)"
                )
            elif len(positional) >= 2:
                locator = _resolve_variable(positional[0], variables)
                text_input = _resolve_variable(positional[1], variables)
            elif positional:
                text_input = _resolve_variable(positional[0], variables)
                locator = "(focused element)"
            else:
                locator = "(focused element)"
        elif len(parts) > 1:
            text_input = parts[1].strip()
            text_input = _resolve_variable(text_input, variables)
    
    # Create minimal ElementInfo from locator
    element_info = _create_element_info_from_locator(locator)
    
    return RecordedStep(
        step_number=step_number,
        action=action_type,
        element_info=element_info,
        text_input=text_input,
        locator_override=locator,  # Use the locator as override since we don't have full element info
    )


def _parse_sleep_duration(line: str) -> float:
    """Parse a 'Sleep    4.7s' line and return the duration in seconds."""
    match = re.search(r"sleep\s+([\d.]+)\s*(s|sec|secs|seconds?|ms|milliseconds?|m|min|mins|minutes?)?", line, re.IGNORECASE)
    if not match:
        return 0.0
    try:
        value = float(match.group(1))
    except ValueError:
        return 0.0
    unit = (match.group(2) or "s").lower()
    if unit.startswith("ms") or unit.startswith("millisecond"):
        return value / 1000.0
    if unit in ("m", "min", "mins") or unit.startswith("minute"):
        return value * 60.0
    return value


def _resolve_variable(value: str, variables: dict[str, str]) -> str:
    """
    Resolve variable references in a value.

    ${VAR_NAME} -> actual value from variables dict
    """
    if not value:
        return value
    
    # Match ${...} pattern
    def replace_var(match):
        var_name = match.group(1)
        return variables.get(var_name, match.group(0))
    
    return re.sub(r"\$\{([^}]+)\}", replace_var, value)


def _create_element_info_from_locator(locator: str) -> ElementInfo:
    """
    Create a minimal ElementInfo from a locator string.

    This is used when loading a .robot file where we don't have
    the full element properties - just the locator.
    """
    name = ""
    automation_id = ""
    control_type_name = ""
    class_name = ""
    path = ""
    
    if not locator:
        return ElementInfo(name="(unknown)")
    
    locator_lower = locator.lower()
    
    # Parse locator components
    if locator_lower.startswith("id:"):
        automation_id = locator[3:].split(" and ")[0].strip()
    elif locator_lower.startswith("name:"):
        name = locator[5:].split(" and ")[0].strip()
    elif locator_lower.startswith("path:"):
        path = locator[5:].strip()
    elif locator_lower.startswith("class:"):
        class_name = locator[6:].split(" and ")[0].strip()
    elif locator_lower.startswith("type:"):
        control_type_name = locator[5:].split(" and ")[0].strip()
    elif _is_path_format(locator):
        path = locator
    else:
        # Assume it's an automation ID or name
        name = locator
    
    # Try to extract type from combined locator
    if " and type:" in locator_lower:
        type_match = re.search(r"type:(\w+)", locator_lower)
        if type_match:
            control_type_name = type_match.group(1).title()
    
    # Create display name
    display_name = automation_id or name or path or locator[:30]
    
    return ElementInfo(
        name=name or display_name,
        automation_id=automation_id,
        class_name=class_name,
        control_type_name=control_type_name or "Control",
        path=path,
    )


def _is_path_format(locator: str) -> bool:
    """Check if locator is a raw path format like '1|2|3|4'."""
    if not locator:
        return False
    # Remove "path:" prefix if present
    path = locator.replace("path:", "").strip()
    parts = path.split("|")
    return all(p.strip().isdigit() for p in parts) and len(parts) > 0
