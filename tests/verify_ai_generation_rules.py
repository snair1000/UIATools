"""Verify AI generation rules: Control Window, Set Anchor, sleeps, Send Keys."""

import sys

sys.path.insert(0, r"c:\UIATools")

from src.ai.script_builder import GeneratedStep, ScriptBuilder
from src.core.recorder import ActionType
from src.core.uia_wrapper import ElementInfo
from src.repository.screen_db import ElementRecord, RecordedEvent


def _rec(eid, path, name="", aid="", ctype="ButtonControl", cls=""):
    return ElementRecord(
        element_id=eid, screen_id=1, path=path, depth=path.count("|") + 1,
        rect=(0, 0, 10, 10),
        element_info=ElementInfo(
            name=name, automation_id=aid, control_type_name=ctype, class_name=cls
        ),
    )


def _ev(t, x=10, y=10, title="Main App Window"):
    return RecordedEvent(
        seq=0, t_offset=t, event_type="click", x=x, y=y,
        window_title=title, process_name="app.exe", window_rect=(0, 0, 800, 600),
    )


builder = ScriptBuilder.__new__(ScriptBuilder)  # skip __init__ (no repo/llm needed)

steps = [
    # 1. Click a button in main window
    GeneratedStep(
        step_number=1, event=_ev(0.0), action=ActionType.CLICK,
        locator="id:FileFindPatientDynamic", keyword_name="Open Find Patient",
        confidence=0.9, window_locator="name:Main App Window",
        element=_rec(1, "path:1|3|1", aid="FileFindPatientDynamic"),
    ),
    # 2. Dropdown (Pane cmbIDType) with typed value - after 5.2s pause
    GeneratedStep(
        step_number=2, event=_ev(5.2), action=ActionType.SELECT, text="MRN",
        locator="id:cmbIDType", keyword_name="Select ID Type",
        confidence=0.9, wait_before=5.2, window_locator="name:Main App Window",
        element=_rec(2, "path:1|3|2", aid="cmbIDType", ctype="PaneControl"),
    ),
    # 3. Edit field typed value (Set Value from LLM -> must become Send Keys)
    GeneratedStep(
        step_number=3, event=_ev(8.0), action=ActionType.SET_VALUE,
        text="20000006236841", locator="id:xaTxtId", keyword_name="Enter Patient ID",
        confidence=0.9, wait_before=2.8, window_locator="name:Main App Window",
        element=_rec(3, "path:1|3|3", aid="xaTxtId", ctype="EditControl"),
    ),
    # 4. Special key TAB (no locator)
    GeneratedStep(
        step_number=4, event=RecordedEvent(seq=0, t_offset=8.5, event_type="key"),
        action=ActionType.SEND_KEYS, text="{TAB}", keyword_name="Press TAB",
        confidence=1.0,
    ),
    # 5. Click inside a WebView2-hosted screen in a different window
    GeneratedStep(
        step_number=5, event=_ev(15.0, title="Patient Chart"),
        action=ActionType.CLICK, locator="name:Sign Note and type:ButtonControl",
        keyword_name="Sign Note", confidence=0.85, wait_before=6.5,
        window_locator="name:Patient Chart",
        anchor_locators=["class:Chrome_WidgetWin_1", "id:notePanel"],
        element=_rec(5, "path:1|4|2|7|3", name="Sign Note", cls="WebButton"),
    ),
]

recorded = builder.to_recorded_steps(steps)
print("RecordedSteps:")
for s in recorded:
    print(f"  {s.step_number}. {s.action.value:10s} loc={s.locator!r} text={s.text_input!r} "
          f"win={s.window_locator!r} anchors={s.anchor_locators} delay_after={s.delay_after}")

from src.export.rf_code_generator import generate_robot_file

robot = generate_robot_file(recorded, task_name="AI Generated Task")
print("\n" + "=" * 70)
print(robot)
print("=" * 70)

# Round-trip: parse it back
from src.export.rf_parser import parse_robot_content

pr = parse_robot_content(robot)
print("\nParsed back:")
print("window_locator:", repr(pr.window_locator))
for i, s in enumerate(pr.steps, 1):
    print(f"  {i}. {s.action.value:10s} {s.locator!r} text={s.text_input!r} "
          f"wait_after={s.wait_after_action}")

# Assertions
assert pr.window_locator == "name:Main App Window", pr.window_locator
acts = [(s.action, s.locator) for s in pr.steps]
assert "Control Window    ${WIN_PATIENT_CHART}" in robot
assert "Set Anchor    ${ANCHOR_CHROME_WIDGETWIN_1}" in robot
assert "Set Anchor    ${ANCHOR_NOTEPANEL}" in robot
assert "Send Keys    ${LOCATOR_PANE_CMBIDTYPE}    ${VALUE_CMBIDTYPE}" in robot
assert "Click    ${LOCATOR_PANE_CMBIDTYPE}" in robot  # dropdown: click first
assert "Send Keys    ${LOCATOR_EDIT_XATXTID}    ${VALUE_XATXTID}" in robot
assert "Send Keys    keys={TAB}" in robot
assert "Sleep    5.2s" in robot and "Sleep    6.5s" in robot
# Parsed Send Keys with locator keeps the locator
sk = [s for s in pr.steps if s.action.value == "Send Keys" and s.locator != "(focused element)"]
assert len(sk) == 2, [s.locator for s in sk]
assert sk[0].locator == "id:cmbIDType" and sk[0].text_input == "MRN"
print("\nALL CHECKS PASSED")
