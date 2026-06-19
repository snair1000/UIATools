"""
step_executor.py - Executes recorded interaction steps.

Provides the ability to replay recorded steps by:
  - Finding elements using various locator strategies (id, name, path, etc.)
  - Performing click, double-click, right-click, type text, set value actions
  - Supporting delays between steps and wait-for-element functionality
  - Reporting progress and errors via callbacks
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import uiautomation as auto

from src.core.recorder import ActionType, RecordedStep
from src.core.uia_wrapper import ElementInfo


class ExecutionStatus(Enum):
    """Status of step execution."""
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass
class StepResult:
    """Result of executing a single step."""
    step: RecordedStep
    status: ExecutionStatus
    message: str = ""
    duration: float = 0.0  # seconds


@dataclass
class ExecutionState:
    """Current state of the executor."""
    is_running: bool = False
    is_paused: bool = False
    current_step_index: int = -1
    total_steps: int = 0
    results: list[StepResult] = field(default_factory=list)
    start_time: float = 0.0
    should_stop: bool = False


class StepExecutor:
    """
    Executes recorded interaction steps.
    
    Usage:
        executor = StepExecutor()
        executor.set_on_step_complete(callback)
        executor.execute_all(steps)
    
    Or step-by-step:
        executor.execute_step(step)
    """

    def __init__(self):
        self._state = ExecutionState()
        self._lock = threading.Lock()
        
        # Callbacks
        self._on_step_start: Optional[Callable[[int, RecordedStep], None]] = None
        self._on_step_complete: Optional[Callable[[int, StepResult], None]] = None
        self._on_execution_complete: Optional[Callable[[list[StepResult]], None]] = None
        self._on_status_update: Optional[Callable[[str], None]] = None
        
        # Execution settings
        self.delay_between_steps: float = 0.5  # seconds
        self.wait_timeout: float = 10.0  # seconds for Wait For Element
        self.retry_count: int = 1  # number of retries for failed actions
        self.click_delay: float = 0.1  # small delay after clicks
        self.search_depth: int = 25  # max depth for element searches
        self.search_timeout: float = 5.0  # seconds to wait for element to exist
        
        # Wait-for-ready settings
        self.auto_wait_for_ready: bool = True  # wait for element to be visible/clickable before action
        self.auto_wait_after_action: float = 0.3  # seconds to wait after action for UI to settle
        self.wait_poll_interval: float = 0.2  # polling interval for wait conditions
        
        # Target window for scoped searches (optional)
        self._target_window: Optional[auto.Control] = None

    def set_target_window(self, window: Optional[auto.Control]):
        """Set a target window to scope element searches (improves performance and accuracy)."""
        self._target_window = window

    def get_search_root(self) -> auto.Control:
        """Get the root element for searches (target window if set, else Desktop)."""
        if self._target_window is not None:
            try:
                # Verify window is still valid
                _ = self._target_window.Name
                return self._target_window
            except Exception:
                self._target_window = None
        return auto.GetRootControl()

    @property
    def is_running(self) -> bool:
        return self._state.is_running

    @property
    def is_paused(self) -> bool:
        return self._state.is_paused

    @property
    def current_step_index(self) -> int:
        return self._state.current_step_index

    @property
    def results(self) -> list[StepResult]:
        return list(self._state.results)

    def set_on_step_start(self, callback: Optional[Callable[[int, RecordedStep], None]]):
        """Set callback called before each step executes."""
        self._on_step_start = callback

    def set_on_step_complete(self, callback: Optional[Callable[[int, StepResult], None]]):
        """Set callback called after each step completes."""
        self._on_step_complete = callback

    def set_on_execution_complete(self, callback: Optional[Callable[[list[StepResult]], None]]):
        """Set callback called when all steps have been executed."""
        self._on_execution_complete = callback

    def set_on_status_update(self, callback: Optional[Callable[[str], None]]):
        """Set callback for status messages."""
        self._on_status_update = callback

    def _update_status(self, message: str):
        """Send a status update."""
        if self._on_status_update:
            try:
                self._on_status_update(message)
            except Exception:
                pass

    def execute_all(
        self,
        steps: list[RecordedStep],
        start_from: int = 0,
        threaded: bool = True,
    ):
        """
        Execute all recorded steps.
        
        Args:
            steps: List of steps to execute.
            start_from: Index to start from (for resume after pause).
            threaded: If True, run in a background thread.
        """
        if self._state.is_running:
            return

        def _run():
            self._execute_steps_internal(steps, start_from)

        if threaded:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
        else:
            _run()

    def execute_single_step(self, step: RecordedStep) -> StepResult:
        """Execute a single step synchronously."""
        return self._execute_one_step(step, 0)

    def _execute_steps_internal(self, steps: list[RecordedStep], start_from: int):
        """Internal method to execute steps (runs on worker thread)."""
        # Initialize COM for this thread
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(0)
        except Exception:
            pass

        with self._lock:
            self._state.is_running = True
            self._state.is_paused = False
            self._state.should_stop = False
            self._state.total_steps = len(steps)
            self._state.start_time = time.time()
            if start_from == 0:
                self._state.results.clear()

        self._update_status(f"Starting execution of {len(steps)} steps...")

        for i in range(start_from, len(steps)):
            # Check for stop/pause
            with self._lock:
                if self._state.should_stop:
                    self._update_status("Execution stopped by user.")
                    break
                if self._state.is_paused:
                    self._update_status(f"Paused at step {i + 1}.")
                    break
                self._state.current_step_index = i

            step = steps[i]
            
            if not step.enabled:
                result = StepResult(
                    step=step,
                    status=ExecutionStatus.SKIPPED,
                    message="Step disabled",
                )
                self._state.results.append(result)
                if self._on_step_complete:
                    try:
                        self._on_step_complete(i, result)
                    except Exception:
                        pass
                continue

            # Notify step start
            if self._on_step_start:
                try:
                    self._on_step_start(i, step)
                except Exception:
                    pass

            self._update_status(f"Executing step {i + 1}/{len(steps)}: {step.action.value}")

            # Execute the step
            result = self._execute_one_step(step, i)
            self._state.results.append(result)

            # Notify step complete
            if self._on_step_complete:
                try:
                    self._on_step_complete(i, result)
                except Exception:
                    pass

            # Stop on failure (optional - could make this configurable)
            if result.status == ExecutionStatus.FAILED:
                self._update_status(f"Step {i + 1} failed: {result.message}")
                # Continue to next step instead of stopping
                # break

            # Delay between steps
            if i < len(steps) - 1 and self.delay_between_steps > 0:
                time.sleep(self.delay_between_steps)

        with self._lock:
            self._state.is_running = False
            self._state.current_step_index = -1

        # Notify execution complete
        elapsed = time.time() - self._state.start_time
        success_count = sum(1 for r in self._state.results if r.status == ExecutionStatus.SUCCESS)
        self._update_status(
            f"Execution complete: {success_count}/{len(self._state.results)} steps succeeded "
            f"in {elapsed:.1f}s"
        )

        if self._on_execution_complete:
            try:
                self._on_execution_complete(self._state.results)
            except Exception:
                pass

    def _execute_one_step(self, step: RecordedStep, index: int) -> StepResult:
        """Execute a single step and return the result."""
        start_time = time.time()

        try:
            # SEND_KEYS doesn't need to find an element - it sends to focused element
            if step.action == ActionType.SEND_KEYS:
                element = None
                locator = "(focused element)"
            else:
                # Find the element using the locator
                locator = step.locator
                element = self._find_element(locator, step.element_info)

                # Fallback: try to find element by stored coordinates if locator failed
                if element is None and step.screen_x and step.screen_y:
                    self._update_status(f"Locator failed, trying coordinates ({step.screen_x}, {step.screen_y})...")
                    try:
                        element = auto.ControlFromPoint(step.screen_x, step.screen_y)
                        if element:
                            self._update_status(f"Found element at coordinates: {element.Name or element.ControlTypeName}")
                    except Exception:
                        pass

            if element is None and step.action not in (ActionType.WAIT_FOR_ELEMENT, ActionType.SEND_KEYS):
                return StepResult(
                    step=step,
                    status=ExecutionStatus.FAILED,
                    message=f"Element not found: {locator}",
                    duration=time.time() - start_time,
                )

            # Wait for element to be ready (visible and clickable) before action
            should_wait_for_ready = step.wait_for_ready or self.auto_wait_for_ready
            if should_wait_for_ready and element is not None:
                if step.action not in (ActionType.GET_ELEMENT, ActionType.WAIT_FOR_ELEMENT, ActionType.SEND_KEYS):
                    self._update_status(f"Waiting for element to be ready...")
                    if not self.wait_for_visible_and_clickable(element, timeout=self.wait_timeout):
                        return StepResult(
                            step=step,
                            status=ExecutionStatus.FAILED,
                            message=f"Element not ready (not visible/enabled): {locator}",
                            duration=time.time() - start_time,
                        )

            # Perform the action
            if step.action == ActionType.CLICK:
                self._perform_click(element)
                message = "Click successful"

            elif step.action == ActionType.RIGHT_CLICK:
                self._perform_click(element, button="right")
                message = "Right click successful"

            elif step.action == ActionType.DOUBLE_CLICK:
                self._perform_double_click(element)
                message = "Double click successful"

            elif step.action == ActionType.TYPE_TEXT:
                self._perform_type_text(element, step.text_input)
                message = f"Typed: {step.text_input[:30]}{'...' if len(step.text_input) > 30 else ''}"

            elif step.action == ActionType.SET_VALUE:
                self._perform_set_value(element, step.text_input)
                message = f"Set value: {step.text_input[:30]}{'...' if len(step.text_input) > 30 else ''}"

            elif step.action == ActionType.SELECT:
                self._perform_select(element, step.text_input)
                message = f"Selected: {step.text_input}"

            elif step.action == ActionType.GET_ELEMENT:
                # Just verify the element exists
                message = "Element found"

            elif step.action == ActionType.WAIT_FOR_ELEMENT:
                element = self._wait_for_element(locator, step.element_info)
                if element:
                    message = "Element appeared"
                else:
                    return StepResult(
                        step=step,
                        status=ExecutionStatus.FAILED,
                        message=f"Timeout waiting for element: {locator}",
                        duration=time.time() - start_time,
                    )

            elif step.action == ActionType.SEND_KEYS:
                # Send keys to currently focused element (no locator needed)
                self._perform_send_keys(step.text_input)
                message = f"Sent keys: {step.text_input[:30]}{'...' if len(step.text_input) > 30 else ''}"

            else:
                message = f"Unknown action: {step.action.value}"

            # Wait after action for UI to settle (if configured)
            wait_after = step.wait_after_action if step.wait_after_action > 0 else self.auto_wait_after_action
            if wait_after > 0:
                time.sleep(wait_after)

            return StepResult(
                step=step,
                status=ExecutionStatus.SUCCESS,
                message=message,
                duration=time.time() - start_time,
            )

        except Exception as e:
            return StepResult(
                step=step,
                status=ExecutionStatus.FAILED,
                message=str(e),
                duration=time.time() - start_time,
            )

    def _find_element(
        self,
        locator: str,
        element_info: Optional[ElementInfo] = None,
    ) -> Optional[auto.Control]:
        """
        Find an element using the locator string.
        
        Supports locator formats:
          - id:AutomationId
          - name:ElementName
          - path:1|2|3|4
          - class:ClassName
          - type:ControlType
          - Combined: id:foo and type:Button
          - coordinates:x,y
        """
        locator = locator.strip()
        locator_lower = locator.lower()
        
        self._update_status(f"Searching for: {locator[:50]}...")
        
        # Handle path-based locator (fastest)
        if locator_lower.startswith("path:"):
            path = locator[5:]
            return self._find_by_path(path)
        
        # Handle raw path format (just numbers with pipes)
        if self._is_path_format(locator):
            return self._find_by_path(locator)

        # Handle coordinate-based locator
        if locator_lower.startswith("coordinates:"):
            coords = locator[12:].split(",")
            if len(coords) == 2:
                try:
                    x, y = int(coords[0]), int(coords[1])
                    return auto.ControlFromPoint(x, y)
                except Exception:
                    pass

        # Handle combined locators (e.g., "id:foo and type:Button")
        if " and " in locator_lower:
            return self._find_by_combined_locator(locator)

        # Handle single locators (case-insensitive prefix, preserve value case)
        if locator_lower.startswith("id:"):
            return self._find_by_automation_id(locator[3:])
        
        if locator_lower.startswith("name:"):
            return self._find_by_name(locator[5:])
        
        if locator_lower.startswith("class:"):
            return self._find_by_class(locator[6:])
        
        if locator_lower.startswith("type:"):
            return self._find_by_type(locator[5:])

        # Fallback: try as AutomationId then Name
        element = self._find_by_automation_id(locator)
        if element:
            return element
        return self._find_by_name(locator)

    def _is_path_format(self, locator: str) -> bool:
        """Check if locator is a raw path format like '1|2|3|4'."""
        parts = locator.split("|")
        return all(p.isdigit() for p in parts) and len(parts) > 0

    def _find_by_path(self, path: str) -> Optional[auto.Control]:
        """Find element by tree path (e.g., '1|2|3|4')."""
        from src.core.uia_wrapper import get_root_element, get_children

        # Parse path indices
        path = path.replace("path:", "").strip()
        try:
            indices = [int(p) for p in path.split("|")]
        except ValueError:
            return None

        if not indices:
            return None

        current = get_root_element()

        # Navigate through the tree
        for idx in indices[1:]:  # Skip the first index (Desktop root is always 1)
            children = get_children(current)
            if idx < 1 or idx > len(children):
                return None
            current = children[idx - 1]  # Convert to 0-based

        return current

    def _find_by_automation_id(self, automation_id: str) -> Optional[auto.Control]:
        """Find element by AutomationId."""
        try:
            root = self.get_search_root()
            element = root.Control(searchDepth=self.search_depth, AutomationId=automation_id)
            if element.Exists(maxSearchSeconds=self.search_timeout):
                return element
        except Exception as e:
            self._update_status(f"Search by AutomationId failed: {e}")
        return None

    def _find_by_name(self, name: str) -> Optional[auto.Control]:
        """Find element by Name."""
        try:
            root = self.get_search_root()
            element = root.Control(searchDepth=self.search_depth, Name=name)
            if element.Exists(maxSearchSeconds=self.search_timeout):
                return element
        except Exception as e:
            self._update_status(f"Search by Name failed: {e}")
        return None

    def _find_by_class(self, class_name: str) -> Optional[auto.Control]:
        """Find element by ClassName."""
        try:
            root = self.get_search_root()
            element = root.Control(searchDepth=self.search_depth, ClassName=class_name)
            if element.Exists(maxSearchSeconds=self.search_timeout):
                return element
        except Exception as e:
            self._update_status(f"Search by ClassName failed: {e}")
        return None

    def _find_by_type(self, control_type: str) -> Optional[auto.Control]:
        """Find element by ControlType."""
        try:
            root = self.get_search_root()
            # Map type name to uiautomation control class
            type_map = {
                "Button": auto.ButtonControl,
                "Edit": auto.EditControl,
                "Text": auto.TextControl,
                "Window": auto.WindowControl,
                "CheckBox": auto.CheckBoxControl,
                "ComboBox": auto.ComboBoxControl,
                "List": auto.ListControl,
                "ListItem": auto.ListItemControl,
                "Menu": auto.MenuControl,
                "MenuItem": auto.MenuItemControl,
                "Tab": auto.TabControl,
                "TabItem": auto.TabItemControl,
                "Tree": auto.TreeControl,
                "TreeItem": auto.TreeItemControl,
                "Pane": auto.PaneControl,
                "Group": auto.GroupControl,
                "RadioButton": auto.RadioButtonControl,
                "Slider": auto.SliderControl,
                "ProgressBar": auto.ProgressBarControl,
                "Hyperlink": auto.HyperlinkControl,
                "Image": auto.ImageControl,
                "Document": auto.DocumentControl,
                "DataGrid": auto.DataGridControl,
                "DataItem": auto.DataItemControl,
                "Table": auto.TableControl,
            }
            ctrl_class = type_map.get(control_type)
            if ctrl_class:
                element = ctrl_class(searchDepth=self.search_depth)
                if element.Exists(maxSearchSeconds=self.search_timeout):
                    return element
        except Exception as e:
            self._update_status(f"Search by ControlType failed: {e}")
        return None

    def _find_by_combined_locator(self, locator: str) -> Optional[auto.Control]:
        """Find element by combined locator (e.g., 'id:foo and type:Button')."""
        # Split by ' and ' (case-insensitive) while preserving original case of values
        import re
        parts = re.split(r'\s+and\s+', locator, flags=re.IGNORECASE)
        
        criteria = {}
        for part in parts:
            part = part.strip()
            # Check prefix case-insensitively, but preserve value case
            part_lower = part.lower()
            if part_lower.startswith("id:"):
                criteria["AutomationId"] = part[3:]  # Preserve original case
            elif part_lower.startswith("name:"):
                criteria["Name"] = part[5:]  # Preserve original case
            elif part_lower.startswith("class:"):
                criteria["ClassName"] = part[6:]  # Preserve original case
            elif part_lower.startswith("type:"):
                criteria["ControlTypeName"] = part[5:]  # Preserve original case

        if not criteria:
            self._update_status(f"No valid criteria parsed from: {locator}")
            return None

        try:
            root = self.get_search_root()
            self._update_status(f"Searching with criteria: {criteria}")
            element = root.Control(searchDepth=self.search_depth, **criteria)
            if element.Exists(maxSearchSeconds=self.search_timeout):
                return element
            self._update_status(f"Element not found with criteria: {criteria}")
        except Exception as e:
            self._update_status(f"Search by combined locator failed: {e}")
        return None

    def _wait_for_element(
        self,
        locator: str,
        element_info: Optional[ElementInfo] = None,
    ) -> Optional[auto.Control]:
        """Wait for an element to appear."""
        start_time = time.time()
        while time.time() - start_time < self.wait_timeout:
            element = self._find_element(locator, element_info)
            if element:
                return element
            time.sleep(0.5)
        return None

    def wait_for_visible_and_clickable(
        self,
        element: auto.Control,
        timeout: float = None,
    ) -> bool:
        """
        Wait for an element to be visible on screen and enabled (clickable).
        
        This is a common wait function that ensures an element is ready for interaction:
        - Element is not offscreen
        - Element is enabled
        - Element has a valid bounding rectangle (not collapsed/hidden)
        
        Args:
            element: The UIA control to wait for.
            timeout: Maximum time to wait in seconds. Uses self.wait_timeout if None.
        
        Returns:
            True if element became ready within timeout, False otherwise.
        """
        if timeout is None:
            timeout = self.wait_timeout
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Check if element is enabled
                is_enabled = element.IsEnabled
                if not is_enabled:
                    time.sleep(self.wait_poll_interval)
                    continue
                
                # Check if element is not offscreen
                is_offscreen = element.IsOffscreen
                if is_offscreen:
                    time.sleep(self.wait_poll_interval)
                    continue
                
                # Check if element has a valid bounding rectangle
                rect = element.BoundingRectangle
                if rect is None:
                    time.sleep(self.wait_poll_interval)
                    continue
                
                # Check rectangle has valid dimensions (not zero-sized)
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0:
                    time.sleep(self.wait_poll_interval)
                    continue
                
                # Element is ready
                return True
                
            except Exception:
                # Element properties might not be accessible, retry
                time.sleep(self.wait_poll_interval)
                continue
        
        return False

    def is_element_ready(self, element: auto.Control) -> bool:
        """
        Check if an element is currently visible and clickable (non-blocking).
        
        Args:
            element: The UIA control to check.
        
        Returns:
            True if element is ready for interaction, False otherwise.
        """
        try:
            # Check enabled
            if not element.IsEnabled:
                return False
            
            # Check not offscreen
            if element.IsOffscreen:
                return False
            
            # Check valid bounding rectangle
            rect = element.BoundingRectangle
            if rect is None:
                return False
            
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return False
            
            return True
        except Exception:
            return False

    def _perform_click(self, element: auto.Control, button: str = "left"):
        """Perform a click on the element."""
        # Try to use the Invoke pattern first (most reliable for buttons)
        if button == "left":
            try:
                invoke = element.GetInvokePattern()
                if invoke:
                    invoke.Invoke()
                    time.sleep(self.click_delay)
                    return
            except Exception:
                pass

        # Fall back to clicking by coordinates
        try:
            rect = element.BoundingRectangle
            x = (rect.left + rect.right) // 2
            y = (rect.top + rect.bottom) // 2
            
            if button == "left":
                auto.Click(x, y)
            else:
                auto.RightClick(x, y)
            
            time.sleep(self.click_delay)
        except Exception as e:
            raise RuntimeError(f"Failed to click element: {e}")

    def _perform_double_click(self, element: auto.Control):
        """Perform a double-click on the element."""
        try:
            rect = element.BoundingRectangle
            x = (rect.left + rect.right) // 2
            y = (rect.top + rect.bottom) // 2
            
            # Use Win32 API for double-click
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            
            # Move to position
            ctypes.windll.user32.SetCursorPos(x, y)
            
            # Perform double-click
            MOUSEEVENTF_LEFTDOWN = 0x0002
            MOUSEEVENTF_LEFTUP = 0x0004
            
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            
            time.sleep(self.click_delay)
        except Exception as e:
            raise RuntimeError(f"Failed to double-click element: {e}")

    def _perform_type_text(self, element: auto.Control, text: str):
        """Type text into the element."""
        # Focus the element first
        try:
            element.SetFocus()
            time.sleep(0.1)
        except Exception:
            # Click to focus
            try:
                rect = element.BoundingRectangle
                x = (rect.left + rect.right) // 2
                y = (rect.top + rect.bottom) // 2
                auto.Click(x, y)
                time.sleep(0.1)
            except Exception:
                pass

        # Type the text using SendKeys
        try:
            auto.SendKeys(text, interval=0.02)
        except Exception as e:
            raise RuntimeError(f"Failed to type text: {e}")

    def _perform_send_keys(self, keys: str):
        """
        Send keystrokes to the currently focused element.
        
        This does not require finding an element first - it sends keys
        directly to whatever has focus. Useful for:
        - Typing into a field after clicking it
        - Sending keyboard shortcuts (e.g., {Ctrl}s, {Enter}, {Tab})
        - Typing text into dialogs or popups
        
        Special keys format:
        - {Enter}, {Tab}, {Escape}, {Backspace}, {Delete}
        - {Ctrl}, {Alt}, {Shift} - modifiers
        - {Ctrl}a - Ctrl+A
        - {F1} through {F12} - function keys
        - {Up}, {Down}, {Left}, {Right} - arrow keys
        """
        try:
            auto.SendKeys(keys, interval=0.02)
        except Exception as e:
            raise RuntimeError(f"Failed to send keys: {e}")

    def _perform_set_value(self, element: auto.Control, text: str):
        """Set the value of an element using the Value pattern."""
        try:
            value_pattern = element.GetValuePattern()
            if value_pattern:
                value_pattern.SetValue(text)
                return
        except Exception:
            pass

        # Fallback: clear and type
        try:
            element.SetFocus()
            time.sleep(0.1)
            # Select all and delete
            auto.SendKeys("{Ctrl}a{Delete}", interval=0.02)
            time.sleep(0.05)
            # Type new text
            auto.SendKeys(text, interval=0.02)
        except Exception as e:
            raise RuntimeError(f"Failed to set value: {e}")

    def _perform_select(self, element: auto.Control, text: str):
        """Select an item in a combo box or list."""
        try:
            # Try SelectionItem pattern
            selection_pattern = element.GetSelectionItemPattern()
            if selection_pattern:
                selection_pattern.Select()
                return
        except Exception:
            pass

        # Try to find the item and click it
        try:
            item = element.Control(Name=text)
            if item.Exists(maxSearchSeconds=2):
                item.Click()
                return
        except Exception:
            pass

        # Try expand and select for combo boxes
        try:
            expand = element.GetExpandCollapsePattern()
            if expand:
                expand.Expand()
                time.sleep(0.2)
                item = element.Control(Name=text)
                if item.Exists(maxSearchSeconds=2):
                    item.Click()
                    return
        except Exception:
            pass

        raise RuntimeError(f"Failed to select item: {text}")

    def pause(self):
        """Pause execution after the current step completes."""
        with self._lock:
            self._state.is_paused = True

    def resume(self, steps: list[RecordedStep]):
        """Resume execution from where it was paused."""
        with self._lock:
            if not self._state.is_paused:
                return
            self._state.is_paused = False
            start_from = self._state.current_step_index + 1

        if start_from < len(steps):
            self.execute_all(steps, start_from=start_from)

    def stop(self):
        """Stop execution."""
        with self._lock:
            self._state.should_stop = True
            self._state.is_paused = False

    def reset(self):
        """Reset the executor state."""
        with self._lock:
            self._state = ExecutionState()
