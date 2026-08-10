"""Verify fixes: window locator parsing, own-process protection, thread COM init.

Simulates 'Load .robot' + 'Run All' without the GUI. Includes a step that
targets a title-bar 'Close' Button, which previously matched UIATools' own
window and closed the app.
"""

import sys
import threading

sys.path.insert(0, r"c:\UIATools")

import uiautomation as auto

# Simulate GUI main-thread usage first (inspector walks tree on startup)
root = auto.GetRootControl()
print("main thread root:", root.Name, flush=True)

from src.export.rf_parser import parse_robot_content
from src.core.step_executor import StepExecutor

ROBOT = """
*** Settings ***
Library    RPA.Windows

*** Variables ***
${WIN}    name:NonExistentTargetApp

*** Tasks ***
Recorded Task
    Control Window    ${WIN}
    Click    name:Close and type:Button
    Click    path:1|2|3
"""

result = parse_robot_content(ROBOT)
print("window_locator:", repr(result.window_locator), flush=True)
assert result.window_locator == "name:NonExistentTargetApp", "window locator not parsed"
assert len(result.steps) == 2, f"expected 2 steps, got {len(result.steps)}"
print("parsed steps:", [(s.action.value, s.locator) for s in result.steps], flush=True)

executor = StepExecutor()
executor.search_timeout = 2.0
executor.wait_timeout = 2.0
executor.delay_between_steps = 0.1
executor.set_target_window_locator(result.window_locator)

done = threading.Event()
outcome = []

def on_complete(results):
    outcome.extend(results)
    done.set()

executor.set_on_execution_complete(on_complete)
executor.set_on_status_update(lambda m: print("STATUS:", m, flush=True))

executor.execute_all(result.steps)

if not done.wait(timeout=120):
    print("TIMEOUT waiting for execution", flush=True)
    sys.exit(2)

for r in outcome:
    print("RESULT:", r.status, r.message, flush=True)

# Verify own-process compare filter directly against this python process
class FakeCtrl:
    ProcessId = __import__("os").getpid()

assert executor._not_own_process(FakeCtrl(), 1) is False
print("own-process filter OK", flush=True)
print("EXECUTION FINISHED NORMALLY - process still alive", flush=True)
