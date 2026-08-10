"""
prompts.py - Prompt templates for AI-assisted script generation.

Design principle: resolution is deterministic (SQL x,y lookup + locator
strategies computed in code); the LLM only makes judgment calls:
  - pick the best candidate element and locator,
  - infer intent (click + typed text -> Set Value vs Click + Type Text),
  - produce a meaningful keyword/step name.

The LLM must answer in strict JSON so responses are machine-parseable.
"""

from __future__ import annotations

import json

from src.repository.screen_db import ElementRecord, RecordedEvent

SYSTEM_PROMPT = """\
You are an RPA automation assistant that converts recorded user interactions
into Robot Framework RPA.Windows steps.

You are given, for each recorded click: the window/screen context, a small
list of candidate UI elements (from a pre-captured UIA tree snapshot) with
ranked locator strategies, and any text the user typed right after the click.

Rules:
- ELEMENT CHOICE: candidates are ordered by geometric evidence - Candidate 1
  is the interactive element whose rectangle contains the exact x,y the user
  clicked, with the smallest area and the center nearest the click point. It
  is almost always the element the user intended. Choose a different
  candidate ONLY if Candidate 1 is clearly a container/decoration (e.g. a
  DataItem, Group, Pane or Text wrapping the real control) or contradicts the
  typed-text evidence - and say why in reasoning. Never pick an element whose
  rectangle is far from the click point just because its Name/AutomationId
  looks more meaningful.
- Locator reliability priority: AutomationId (id:) > Name+Type > Class+Type > path.
  Prefer the most reliable locator offered in the candidate's strategies.
  The locator MUST come from the strategies of the candidate you chose -
  never from another candidate.
- AMBIGUITY: each locator strategy is annotated with how many elements on
  the screen it matches. A locator matching more than 1 element is ambiguous
  and WILL cause the wrong element to be targeted at runtime. Never choose
  an ambiguous locator: fall back to the next unambiguous strategy, or use
  the candidate's path: locator (the tree position is unique and was chosen
  from the exact x,y coordinates the user clicked). Mention this in reasoning.
- WAITS: if the step notes that the user paused before clicking, they were
  most likely waiting for a screen or element to load. A matching Sleep is
  added to the script automatically before this step - factor this into the
  keyword_name/reasoning (e.g. the click likely opens a slow screen), and do
  not lower confidence because of the pause.
- If the user typed text right after clicking an Edit element,
  use action "Set Value" with that text. (The generated script will emit it
  as `Send Keys  <locator>  <text>` - keyboard input is the most compatible
  way to enter values in the target applications.)
- If the clicked element is a ComboBox or any dropdown-like control (this
  includes Pane/Custom controls whose AutomationId suggests a combo, e.g.
  starting with 'cmb', 'cbo' or 'ddl') and the user typed text into it,
  use action "Select" with the typed text as the value. The generated
  script will emit `Click <locator>` followed by `Send Keys <locator>
  <text>` because these dropdowns do not accept Set Value/Select patterns.
  A following TAB or ENTER key confirms the value was committed.
- If the element is not an edit or combobox control, keep "Click" and emit
  the text as a separate "Send Keys" step (handled by the caller - just
  note it).
- If the typed text is marked REDACTED, still choose the element and action,
  and use the placeholder ${SECRET} as the text value.
- Actions you may choose: Click, Right Click, Double Click, Set Value,
  Type Text, Select.
- keyword_name: a short human-readable name for the step, e.g. "Enter Username".
- confidence: 0.0-1.0, your certainty that the chosen element is what the
  user actually clicked. Below 0.7 means the step needs human review.

Respond ONLY with a JSON object of this exact shape:
{
  "candidate_index": <int, 1-based index of chosen candidate>,
  "locator": "<the locator string you chose>",
  "action": "<Click|Right Click|Double Click|Set Value|Type Text|Select>",
  "text": "<text value if action needs one, else empty string>",
  "keyword_name": "<short step name>",
  "confidence": <float>,
  "reasoning": "<one short sentence>"
}
"""


def format_candidate(
    index: int,
    record: ElementRecord,
    strategies: list[dict],
    rel_x: int | None = None,
    rel_y: int | None = None,
) -> str:
    """Format one candidate element with its locator strategies."""
    info = record.element_info
    geometry = f"  WindowRelativeRect: {record.rect}"
    if rel_x is not None and rel_y is not None:
        left, top, right, bottom = record.rect
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        dist = ((rel_x - cx) ** 2 + (rel_y - cy) ** 2) ** 0.5
        geometry += (
            f"  center=({cx}, {cy}), distance from click: {dist:.0f}px, "
            f"area: {max(right - left, 0) * max(bottom - top, 0)}px\u00b2"
        )
    lines = [
        f"Candidate {index}:",
        f"  ControlType: {info.control_type_name}",
        f"  Name: {info.name!r}",
        f"  AutomationId: {info.automation_id!r}",
        f"  ClassName: {info.class_name!r}",
        f"  Path: {record.path}",
        geometry,
        f"  Value: {info.value!r}" if info.value else "",
        "  Locator strategies (best first):",
    ]
    for s in strategies:
        match_count = s.get("match_count", 1)
        suffix = (
            f"  <-- AMBIGUOUS: matches {match_count} elements on this screen, do not use"
            if match_count > 1
            else ""
        )
        lines.append(f"    - [{s['reliability']}] {s['locator']}{suffix}")
    return "\n".join(line for line in lines if line)


def build_step_prompt(
    click_event: RecordedEvent,
    screen_label: str,
    rel_x: int,
    rel_y: int,
    candidates: list[tuple[ElementRecord, list[dict]]],
    following_text: str = "",
    text_redacted: bool = False,
    preferred_locators: dict[int, str] | None = None,
    following_keys: list[str] | None = None,
    previous_choice: dict | None = None,
    user_feedback: str | None = None,
    wait_before_s: float = 0.0,
) -> str:
    """Build the per-click user prompt."""
    parts = [
        f'Screen: "{screen_label}" (window title: "{click_event.window_title}", '
        f"process: {click_event.process_name})",
        f"User {click_event.button}-clicked at window-relative ({rel_x}, {rel_y}).",
    ]
    if wait_before_s > 0:
        parts.append(
            f"The user paused {wait_before_s:.1f} seconds before this click - "
            "most likely waiting for a screen or element to finish loading. "
            f"A 'Sleep  {wait_before_s:.1f}s' will be inserted before this step "
            "automatically."
        )
    if following_text:
        if text_redacted:
            parts.append(
                "Immediately after the click the user typed sensitive text "
                "(REDACTED by the user)."
            )
        else:
            parts.append(f'Immediately after the click the user typed: "{following_text}"')
    if following_keys:
        parts.append(
            "After typing, the user pressed: "
            + ", ".join(following_keys)
            + " (a TAB/ENTER here usually commits a typed dropdown value)."
        )

    parts.append("")
    parts.append(
        f"Candidate elements at that point ({len(candidates)}), "
        "ordered best-first by geometric match to the click:"
    )
    for i, (record, strategies) in enumerate(candidates, start=1):
        parts.append(format_candidate(i, record, strategies, rel_x, rel_y))
        if preferred_locators and record.element_id in preferred_locators:
            parts.append(
                f"  NOTE: locator '{preferred_locators[record.element_id]}' was "
                "chosen for this element in a previous accepted script."
            )
        parts.append("")

    if previous_choice:
        parts.append(
            "Your previous answer for this step was:\n"
            + json.dumps(previous_choice, indent=2)
        )
        parts.append("")
    if user_feedback:
        parts.append(
            "The user reviewed your previous answer and gave this feedback. "
            "Take it into account, reconsider your choice, and explain in "
            "'reasoning' how the feedback changed (or confirmed) your answer:\n"
            f'"{user_feedback}"'
        )
        parts.append("")

    parts.append("Choose the best candidate and respond with the JSON object.")
    return "\n".join(parts)


def parse_step_response(raw: str) -> dict:
    """
    Parse the LLM's JSON response, tolerating markdown fences.

    Returns a dict with keys: candidate_index, locator, action, text,
    keyword_name, confidence, reasoning. Raises ValueError on failure.
    """
    text = raw.strip()
    if text.startswith("```"):
        # Strip markdown code fences
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)
    # Find the outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object in LLM response: {raw[:200]}")
    data = json.loads(text[start : end + 1])

    result = {
        "candidate_index": int(data.get("candidate_index", 1)),
        "locator": str(data.get("locator", "")),
        "action": str(data.get("action", "Click")),
        "text": str(data.get("text", "")),
        "keyword_name": str(data.get("keyword_name", "")),
        "confidence": float(data.get("confidence", 0.0)),
        "reasoning": str(data.get("reasoning", "")),
    }
    if not result["locator"]:
        raise ValueError("LLM response missing 'locator'.")
    return result
