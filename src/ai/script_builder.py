"""
script_builder.py - Orchestrates AI-assisted script generation.

Pipeline (per recorded click):
  1. Match the event's window to a stored screen (title/process, fuzzy).
  2. Convert the click to window-relative coordinates, scaling for any
     window-size difference between capture time and recording time.
  3. SQL lookup: candidate elements whose rects contain the point.
  4. Compute ranked locator strategies per candidate (deterministic).
  5. Ask the LLM to pick the element/locator and infer intent.
  6. Assemble RecordedSteps and render a .robot file via the existing
     rf_code_generator.

The LLM never sees the whole tree - only the top candidates. Redacted
text is never sent to the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from src.ai.llm_client import LLMClient, LLMError
from src.ai.prompts import (
    SYSTEM_PROMPT,
    build_step_prompt,
    parse_step_response,
)
from src.core.recorder import ActionType, RecordedStep
from src.export.locator_strategy import build_locator_strategies
from src.export.rf_code_generator import generate_robot_file
from src.repository.screen_db import (
    ElementRecord,
    RecordedEvent,
    ScreenRecord,
    ScreenRepository,
)

CONFIDENCE_REVIEW_THRESHOLD = 0.7

# Pauses between actions at/above this length are reproduced as Sleep
# statements in the generated script (rule: time gaps while recording
# automatically become sleep time). Very small gaps are just click latency.
WAIT_THRESHOLD_SECONDS = 0.5

_ACTION_MAP = {
    "click": ActionType.CLICK,
    "right click": ActionType.RIGHT_CLICK,
    "double click": ActionType.DOUBLE_CLICK,
    "set value": ActionType.SET_VALUE,
    "type text": ActionType.TYPE_TEXT,
    "select": ActionType.SELECT,
}


@dataclass
class GeneratedStep:
    """One resolved step, ready for review and .robot generation."""

    step_number: int
    event: RecordedEvent
    action: ActionType = ActionType.CLICK
    locator: str = ""
    text: str = ""
    keyword_name: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    needs_review: bool = False
    error: str = ""
    wait_before: float = 0.0  # observed pause before this action (seconds)
    window_locator: str = ""  # locator for the window the click landed in
    anchor_locators: list[str] = field(default_factory=list)  # Set Anchor chain (WebView2)
    screen: Optional[ScreenRecord] = None
    element: Optional[ElementRecord] = None
    candidates: list[tuple[ElementRecord, list[dict]]] = field(default_factory=list)

    @property
    def display_detail(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        detail = f"{self.action.value}  {self.locator}"
        if self.text:
            detail += f'  "{self.text}"'
        return detail


class ScriptBuilder:
    """Builds RPA.Windows scripts from raw recorded events + repository."""

    def __init__(self, repo: ScreenRepository, llm: LLMClient):
        self._repo = repo
        self._llm = llm
        self._screen_elements_cache: dict[int, list[ElementRecord]] = {}

    def build_steps(
        self,
        events: list[RecordedEvent],
        progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> list[GeneratedStep]:
        """
        Resolve recorded events into GeneratedSteps.

        Args:
            events: Raw recorded events in sequence order.
            progress: Optional callback(current, total, message).
            cancel_check: Optional callable returning True to abort.

        Returns:
            List of GeneratedSteps (clicks resolved via repo + LLM;
            special keys become Send Keys steps).
        """
        groups = self._group_events(events)
        steps: list[GeneratedStep] = []
        total = len(groups)
        prev_end_t = 0.0

        for i, (click, typed_text, text_redacted, special_keys, group_end_t) in enumerate(
            groups, 1
        ):
            if cancel_check and cancel_check():
                break
            if progress:
                label = (
                    f"click @ ({click.x}, {click.y})" if click else "keystrokes"
                )
                progress(i, total, f"Resolving step {i}/{total}: {label}")

            if click is None:
                # Keystroke-only group (no preceding click)
                steps.extend(
                    self._keys_only_steps(len(steps) + 1, typed_text, text_redacted, special_keys)
                )
                prev_end_t = max(prev_end_t, group_end_t)
                continue

            # Gap between the previous action and this click -> wait time
            gap = click.t_offset - prev_end_t
            wait_before = round(gap, 1) if gap >= WAIT_THRESHOLD_SECONDS else 0.0

            step = self._resolve_click(
                len(steps) + 1, click, typed_text, text_redacted, special_keys,
                wait_before=wait_before,
            )
            steps.append(step)
            prev_end_t = max(prev_end_t, group_end_t)

            # Special keys after the click (ENTER, TAB...) become Send Keys
            for key_ev in special_keys:
                steps.append(self._send_keys_step(len(steps) + 1, key_ev))

        return steps

    # ── Event grouping ────────────────────────────────────────

    def _group_events(
        self, events: list[RecordedEvent]
    ) -> list[tuple[Optional[RecordedEvent], str, bool, list[RecordedEvent], float]]:
        """
        Group events into (click, typed_text, text_redacted, special_keys,
        group_end_t) where group_end_t is the t_offset of the last event in
        the group (used to compute inter-action wait times).

        A click adopts the immediately following 'keys' event as its typed
        text, and any 'key' (special) events until the next click.
        Leading keystrokes with no click form a (None, ...) group.
        """
        groups: list[tuple[Optional[RecordedEvent], str, bool, list[RecordedEvent], float]] = []
        current_click: Optional[RecordedEvent] = None
        typed_text = ""
        text_redacted = False
        specials: list[RecordedEvent] = []
        has_group = False
        group_end_t = 0.0

        def _flush():
            nonlocal current_click, typed_text, text_redacted, specials, has_group, group_end_t
            if has_group:
                groups.append(
                    (current_click, typed_text, text_redacted, specials, group_end_t)
                )
            current_click = None
            typed_text = ""
            text_redacted = False
            specials = []
            has_group = False
            group_end_t = 0.0

        for ev in events:
            if ev.event_type == "click":
                _flush()
                current_click = ev
                has_group = True
            elif ev.event_type == "keys":
                if not has_group:
                    has_group = True  # keystrokes with no click
                if typed_text and not text_redacted:
                    typed_text += ev.text if not ev.redacted else ""
                else:
                    typed_text = ev.text
                if ev.redacted:
                    text_redacted = True
            elif ev.event_type == "key":
                if not has_group:
                    has_group = True
                specials.append(ev)
            if has_group:
                group_end_t = max(group_end_t, ev.t_offset)
        _flush()
        return groups

    # ── Click resolution ──────────────────────────────────────

    def _resolve_click(
        self,
        step_number: int,
        click: RecordedEvent,
        typed_text: str,
        text_redacted: bool,
        special_keys: list[RecordedEvent] | None = None,
        wait_before: float = 0.0,
    ) -> GeneratedStep:
        step = GeneratedStep(step_number=step_number, event=click, wait_before=wait_before)
        if typed_text:
            step.text = "${SECRET}" if text_redacted else typed_text

        # 1. Match screen. The same window title can have several stored
        # variants (one per tab state) - search ALL of them and keep the
        # variant whose stored element best fits this click point.
        matches = self._repo.match_screen(click.window_title, click.process_name)
        if not matches:
            step.needs_review = True
            step.error = (
                f"No stored screen matches window '{click.window_title}' "
                f"({click.process_name}). Capture it in the Repository tab."
            )
            return step

        screen, rel_x, rel_y, candidates_recs = self._pick_screen_variant(
            click, matches
        )
        step.screen = screen
        step.window_locator = self._window_locator_for(click, screen)

        if not candidates_recs:
            variant_labels = ", ".join(
                f"'{s.label}'" for s, _ in matches[:5]
            )
            rel_x, rel_y = self._to_screen_coords(click, screen)
            step.needs_review = True
            step.error = (
                f"No stored element found at window-relative ({rel_x}, {rel_y}) "
                f"in any stored variant of this window ({variant_labels}). "
                "If the window has tabs, capture each tab state as its own "
                "screen in the Repository tab."
            )
            return step

        # Guard: if the deepest thing stored at this point is the WebView2
        # host pane itself, the screen snapshot was captured before the
        # browser exposed its accessibility tree - the real (web) element
        # is missing from the repository. Flag instead of emitting a click
        # on 'Chrome Legacy Window'.
        best = candidates_recs[0]
        if self._is_webview_host(best.element_info) or (
            best.element_info.control_type_name in ("PaneControl", "DocumentControl")
            and (best.element_info.framework_id or "") == "Chrome"
            and not any(
                r.depth > best.depth for r in candidates_recs
            )
        ):
            step.needs_review = True
            step.error = (
                f"Only the WebView2 host pane was stored at ({rel_x}, {rel_y}) on "
                f"screen '{screen.label}' - the web content (e.g. the checkbox you "
                "clicked) is missing from the snapshot. Re-capture this screen in "
                "the Repository tab with the page fully loaded."
            )
            return step

        # 4. Locator strategies (deterministic), annotated with screen-wide
        # ambiguity: how many elements on this screen each locator matches.
        candidates = [
            (rec, build_locator_strategies(rec.element_info)) for rec in candidates_recs
        ]
        self._annotate_ambiguity(screen.screen_id, candidates)
        step.candidates = candidates

        # Preferred locators from earlier accepted scripts
        preferred: dict[int, str] = {}
        for rec, _ in candidates:
            prev = self._repo.get_preferred_locator(rec.element_id)
            if prev:
                preferred[rec.element_id] = prev

        # 5. LLM judgment
        prompt = build_step_prompt(
            click_event=click,
            screen_label=screen.label,
            rel_x=rel_x,
            rel_y=rel_y,
            candidates=candidates,
            following_text=step.text if not text_redacted else "(sensitive)",
            text_redacted=text_redacted,
            preferred_locators=preferred or None,
            following_keys=[ev.vk_name for ev in special_keys] if special_keys else None,
            wait_before_s=wait_before,
        )
        try:
            raw = self._llm.generate(SYSTEM_PROMPT, prompt, json_mode=True)
            result = parse_step_response(raw)
        except (LLMError, ValueError) as e:
            # Deterministic fallback: best candidate, best unambiguous strategy
            rec, strategies = candidates[0]
            step.element = rec
            step.locator = self._best_unambiguous_locator(rec, strategies)
            step.anchor_locators = self._compute_anchors(screen.screen_id, rec)
            if step.text:
                ctype = (rec.element_info.control_type_name or "").lower()
                step.action = (
                    ActionType.SELECT if "combobox" in ctype else ActionType.SET_VALUE
                )
            else:
                step.action = ActionType.CLICK
            step.needs_review = True
            step.error = f"LLM unavailable, used best-guess locator. ({e})"
            return step

        idx = max(1, min(result["candidate_index"], len(candidates))) - 1
        step.element = candidates[idx][0]
        step.locator = self._validated_locator(
            result["locator"], candidates[idx][0], candidates[idx][1]
        )
        step.anchor_locators = self._compute_anchors(screen.screen_id, step.element)
        step.action = _ACTION_MAP.get(result["action"].lower(), ActionType.CLICK)
        if result["text"]:
            step.text = result["text"]
        step.keyword_name = result["keyword_name"]
        step.confidence = result["confidence"]
        step.reasoning = result["reasoning"]
        step.needs_review = result["confidence"] < CONFIDENCE_REVIEW_THRESHOLD
        return step

    def _validated_locator(
        self, locator: str, rec: ElementRecord, strategies: list[dict]
    ) -> str:
        """
        Ensure the LLM's locator actually belongs to the chosen candidate
        (and is unambiguous). Otherwise substitute the candidate's best
        unambiguous strategy - the LLM must not mix element A with element
        B's locator.
        """
        for s in strategies:
            if s["locator"] == locator and s.get("match_count", 1) == 1:
                return locator
        if locator == rec.path:
            return locator
        return self._best_unambiguous_locator(rec, strategies)

    # ── Window & anchor context ───────────────────────────────

    # Control types the user directly interacts with. When several stored
    # elements contain the click point, these beat containers/decorations
    # (DataItem, Group, Text, Pane...) that merely surround the same point.
    _INTERACTIVE_TYPES = frozenset({
        "CheckBoxControl", "ButtonControl", "RadioButtonControl",
        "EditControl", "ComboBoxControl", "HyperlinkControl",
        "MenuItemControl", "TabItemControl", "ListItemControl",
        "TreeItemControl", "SplitButtonControl", "SliderControl",
        "SpinnerControl",
    })

    @classmethod
    def _candidate_key(cls, rec: ElementRecord, rel_x: int, rel_y: int):
        """Sort key: interactive controls first, then smallest rect, then
        center closest to the click point, then deepest in the tree."""
        left, top, right, bottom = rec.rect
        area = max((right - left) * (bottom - top), 1)
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0
        dist = ((rel_x - cx) ** 2 + (rel_y - cy) ** 2) ** 0.5
        interactive = (
            0 if rec.element_info.control_type_name in cls._INTERACTIVE_TYPES
            else 1
        )
        return (interactive, area, dist, -rec.depth)

    @classmethod
    def _rank_candidates(
        cls, recs: list[ElementRecord], rel_x: int, rel_y: int
    ) -> list[ElementRecord]:
        """
        Order candidates so the first one is the element the user actually
        clicked: interactive controls first, then smallest rect, then the
        center closest to the click point, then deepest in the tree.
        """
        return sorted(recs, key=lambda r: cls._candidate_key(r, rel_x, rel_y))

    def _pick_screen_variant(
        self,
        click: RecordedEvent,
        matches: list[tuple[ScreenRecord, float]],
    ) -> tuple[ScreenRecord, int, int, list[ElementRecord]]:
        """
        Among all stored screens matching the clicked window (e.g. one
        capture per tab state of the same window), pick the variant whose
        stored element at the click point looks most like the real target.

        Considers every match tied with the best title/process score,
        ranks each variant's candidates, and compares the winners across
        variants with _candidate_key. Newer captures win ties. Returns
        (screen, rel_x, rel_y, ranked_candidates); candidates is [] when
        no variant has an element at the click point.
        """
        best_score = matches[0][1]
        variants = [s for s, sc in matches if sc >= best_score - 0.05]

        best: Optional[tuple] = None  # (key, -screen_id, screen, rel_x, rel_y, ranked)
        for screen in variants:
            rel_x, rel_y = self._to_screen_coords(click, screen)
            recs = self._repo.find_elements_at(screen.screen_id, rel_x, rel_y)
            if not recs:
                continue
            ranked = self._rank_candidates(recs, rel_x, rel_y)
            top = ranked[0]
            # Penalise variants where only a webview host pane covers the
            # point - another variant with real content should win.
            key = self._candidate_key(top, rel_x, rel_y)
            if self._is_webview_host(top.element_info):
                key = (key[0] + 2,) + key[1:]
            entry = (key, -screen.screen_id, screen, rel_x, rel_y, ranked)
            if best is None or entry[:2] < best[:2]:
                best = entry

        if best is None:
            return matches[0][0], 0, 0, []
        _, _, screen, rel_x, rel_y, ranked = best
        return screen, rel_x, rel_y, ranked

    @staticmethod
    def _window_locator_for(click: RecordedEvent, screen: ScreenRecord) -> str:
        """Locator for the window that had focus when the user clicked."""
        title = (click.window_title or screen.window_title or "").strip()
        if title:
            return f"name:{title}"
        if screen.class_name:
            return f"class:{screen.class_name}"
        return ""

    @staticmethod
    def _is_webview_host(info) -> bool:
        """True if the element is a WebView2/Chromium host panel."""
        cls = (info.class_name or "")
        if cls.startswith("Chrome_WidgetWin") or "WebView2" in cls:
            return True
        if cls == "Chrome_RenderWidgetHostHWND" or info.name == "Chrome Legacy Window":
            return True
        return False

    def _compute_anchors(self, screen_id: int, rec: ElementRecord) -> list[str]:
        """
        For elements hosted inside a WebView2 control, build a Set Anchor
        chain: [webview host panel, nearest panel ancestor of the element].
        Returns [] for ordinary (non-webview) elements.
        """
        if not rec.path.startswith("path:"):
            return []
        by_path = {
            e.path: e for e in self._screen_elements(screen_id)
        }
        # Ancestor chain from root to the element's parent (path prefixes)
        parts = rec.path[5:].split("|")
        ancestors: list[ElementRecord] = []
        for i in range(1, len(parts)):
            anc = by_path.get("path:" + "|".join(parts[:i]))
            if anc is not None:
                ancestors.append(anc)

        # Outermost WebView2 host in the chain
        host: Optional[ElementRecord] = None
        host_depth_idx = -1
        for i, anc in enumerate(ancestors):
            if self._is_webview_host(anc.element_info):
                host = anc
                host_depth_idx = i
                break
        if host is None:
            # Element not inside a webview - no anchors needed
            if (rec.element_info.framework_id or "") != "Chrome":
                return []
            # Framework says Chrome but no host stored - nothing to anchor to
            return []

        anchors = [self._anchor_locator(screen_id, host)]

        # Nearest panel-like ancestor below the host, closest to the element
        panel_types = {"PaneControl", "GroupControl", "CustomControl", "DocumentControl"}
        inner: Optional[ElementRecord] = None
        for anc in reversed(ancestors[host_depth_idx + 1:]):
            if anc.element_info.control_type_name in panel_types:
                # Prefer a panel we can locate unambiguously without a path
                loc = self._anchor_locator(screen_id, anc, require_non_path=True)
                if loc:
                    inner = anc
                    anchors.append(loc)
                    break
                if inner is None:
                    inner = anc  # remember deepest panel as fallback
        if len(anchors) == 1 and inner is not None:
            anchors.append(self._anchor_locator(screen_id, inner))

        # Drop duplicates while preserving order
        seen: set[str] = set()
        result = []
        for a in anchors:
            if a and a not in seen:
                seen.add(a)
                result.append(a)
        return result

    def _anchor_locator(
        self, screen_id: int, rec: ElementRecord, require_non_path: bool = False
    ) -> str:
        """Best unambiguous locator for an anchor element (path as fallback)."""
        strategies = build_locator_strategies(rec.element_info)
        pair = [(rec, strategies)]
        self._annotate_ambiguity(screen_id, pair)
        for s in strategies:
            if s.get("match_count", 1) == 1 and not s["locator"].startswith("path:"):
                return s["locator"]
        if require_non_path:
            return ""
        return rec.path

    # ── Locator ambiguity ─────────────────────────────────────

    def _screen_elements(self, screen_id: int) -> list[ElementRecord]:
        if screen_id not in self._screen_elements_cache:
            self._screen_elements_cache[screen_id] = self._repo.list_elements(screen_id)
        return self._screen_elements_cache[screen_id]

    def _annotate_ambiguity(
        self, screen_id: int, candidates: list[tuple[ElementRecord, list[dict]]]
    ):
        """
        Add a 'match_count' to each locator strategy: the number of elements
        on the screen snapshot that share the properties the locator uses.
        A count > 1 means the locator is ambiguous and would be unreliable.
        """
        elements = self._screen_elements(screen_id)

        def _count(predicate) -> int:
            return sum(1 for e in elements if predicate(e.element_info))

        for rec, strategies in candidates:
            info = rec.element_info
            for s in strategies:
                stype = s.get("type", "")
                if stype == "AutomationId":
                    n = _count(lambda i: i.automation_id == info.automation_id)
                elif stype == "AutomationId+Type":
                    n = _count(
                        lambda i: i.automation_id == info.automation_id
                        and i.control_type_name == info.control_type_name
                    )
                elif stype in ("Name+Type",):
                    n = _count(
                        lambda i: i.name == info.name
                        and i.control_type_name == info.control_type_name
                    )
                elif stype == "Name":
                    n = _count(lambda i: i.name == info.name)
                elif "Class" in stype:
                    n = _count(
                        lambda i: i.class_name == info.class_name
                        and i.control_type_name == info.control_type_name
                    )
                elif stype == "Path" or s["locator"].startswith("path:"):
                    n = 1  # tree position is unique by construction
                else:
                    n = 1
                s["match_count"] = max(n, 1)

    def _best_unambiguous_locator(
        self, rec: ElementRecord, strategies: list[dict]
    ) -> str:
        """Best-ranked strategy that matches exactly one element, else path."""
        for s in strategies:
            if s.get("match_count", 1) == 1:
                return s["locator"]
        return rec.path

    def refine_step(self, step: GeneratedStep, feedback: str) -> GeneratedStep:
        """
        Re-run the LLM judgment for one step with user feedback so the
        model can reconsider its element/locator/action choice.

        Mutates and returns the step. Raises LLMError/ValueError on failure
        (the step is left unchanged in that case).
        """
        if step.event.event_type != "click" or not step.candidates or not step.screen:
            raise LLMError(
                "This step has no candidate elements to reason about. "
                "Only resolved click steps can be refined."
            )
        click = step.event
        screen = step.screen
        rel_x, rel_y = self._to_screen_coords(click, screen)

        preferred: dict[int, str] = {}
        for rec, _ in step.candidates:
            prev = self._repo.get_preferred_locator(rec.element_id)
            if prev:
                preferred[rec.element_id] = prev

        previous_choice = {
            "locator": step.locator,
            "action": step.action.value,
            "keyword_name": step.keyword_name,
            "confidence": step.confidence,
            "reasoning": step.reasoning,
        }
        text_redacted = step.text == "${SECRET}"
        prompt = build_step_prompt(
            click_event=click,
            screen_label=screen.label,
            rel_x=rel_x,
            rel_y=rel_y,
            candidates=step.candidates,
            following_text="(sensitive)" if text_redacted else step.text,
            text_redacted=text_redacted,
            preferred_locators=preferred or None,
            previous_choice=previous_choice,
            user_feedback=feedback,
            wait_before_s=step.wait_before,
        )
        raw = self._llm.generate(SYSTEM_PROMPT, prompt, json_mode=True)
        result = parse_step_response(raw)

        idx = max(1, min(result["candidate_index"], len(step.candidates))) - 1
        step.element = step.candidates[idx][0]
        step.locator = self._validated_locator(
            result["locator"], step.candidates[idx][0], step.candidates[idx][1]
        )
        step.anchor_locators = self._compute_anchors(screen.screen_id, step.element)
        step.action = _ACTION_MAP.get(result["action"].lower(), ActionType.CLICK)
        if result["text"] and not text_redacted:
            step.text = result["text"]
        step.keyword_name = result["keyword_name"]
        step.confidence = result["confidence"]
        step.reasoning = result["reasoning"]
        step.needs_review = result["confidence"] < CONFIDENCE_REVIEW_THRESHOLD
        step.error = ""
        return step

    def _to_screen_coords(
        self, click: RecordedEvent, screen: ScreenRecord
    ) -> tuple[int, int]:
        """Convert absolute click coords to capture-time window-relative."""
        rec_left, rec_top, rec_right, rec_bottom = click.window_rect
        cap_left, cap_top, cap_right, cap_bottom = screen.window_rect

        rel_x = click.x - rec_left
        rel_y = click.y - rec_top

        # Scale if the window size differs between capture and recording
        rec_w = max(rec_right - rec_left, 1)
        rec_h = max(rec_bottom - rec_top, 1)
        cap_w = max(cap_right - cap_left, 1)
        cap_h = max(cap_bottom - cap_top, 1)
        if (rec_w, rec_h) != (cap_w, cap_h):
            rel_x = int(rel_x * cap_w / rec_w)
            rel_y = int(rel_y * cap_h / rec_h)
        return rel_x, rel_y

    # ── Non-click steps ───────────────────────────────────────

    def _send_keys_step(self, step_number: int, key_ev: RecordedEvent) -> GeneratedStep:
        step = GeneratedStep(
            step_number=step_number,
            event=key_ev,
            action=ActionType.SEND_KEYS,
            text="{" + key_ev.vk_name + "}",
            keyword_name=f"Press {key_ev.vk_name}",
            confidence=1.0,
        )
        return step

    def _keys_only_steps(
        self,
        start_number: int,
        typed_text: str,
        text_redacted: bool,
        special_keys: list[RecordedEvent],
    ) -> list[GeneratedStep]:
        steps: list[GeneratedStep] = []
        n = start_number
        if typed_text:
            steps.append(
                GeneratedStep(
                    step_number=n,
                    event=RecordedEvent(seq=0, t_offset=0.0, event_type="keys"),
                    action=ActionType.SEND_KEYS,
                    text="${SECRET}" if text_redacted else typed_text,
                    keyword_name="Type Text (no click)",
                    confidence=1.0,
                    needs_review=text_redacted,
                )
            )
            n += 1
        for key_ev in special_keys:
            steps.append(self._send_keys_step(n, key_ev))
            n += 1
        return steps

    # ── .robot assembly ───────────────────────────────────────

    @staticmethod
    def _is_dropdown(gs: GeneratedStep) -> bool:
        """Dropdown-like: ComboBox control, or the LLM judged it a Select."""
        if gs.action == ActionType.SELECT:
            return True
        if gs.element:
            ctype = (gs.element.element_info.control_type_name or "").lower()
            if "combobox" in ctype:
                return True
            aid = (gs.element.element_info.automation_id or "").lower()
            if aid.startswith(("cmb", "cbo", "ddl")) or "dropdown" in aid:
                return True
        return False

    def to_recorded_steps(self, gen_steps: list[GeneratedStep]) -> list[RecordedStep]:
        """
        Convert GeneratedSteps into RecordedSteps for rf_code_generator.

        Conventions enforced here (independent of what the LLM chose):
          - Typed values are always emitted as `Send Keys  <locator>  <text>`.
          - Dropdown-like controls get `Click <locator>` first, then
            `Send Keys <locator> <text>` (Set Value/Select are not reliable
            on the target apps' custom dropdowns).
          - Observed pauses become a Sleep after the previous step.
        """
        return [step for _, step in self.to_recorded_steps_mapped(gen_steps)]

    def to_recorded_steps_mapped(
        self, gen_steps: list[GeneratedStep]
    ) -> list[tuple[int, RecordedStep]]:
        """
        Like to_recorded_steps, but each RecordedStep is paired with the
        index of the GeneratedStep it came from (one generated step can
        expand into Click + Send Keys). Used by the review dialog's test
        run to map executor results back to review rows.
        """
        from src.core.uia_wrapper import ElementInfo

        recorded: list[tuple[int, RecordedStep]] = []

        def _append(src_idx: int, step: RecordedStep):
            step.step_number = len(recorded) + 1
            recorded.append((src_idx, step))

        for gi, gs in enumerate(gen_steps):
            if gs.error and not gs.locator:
                continue  # unresolvable step - skipped (flagged in review UI)
            info = gs.element.element_info if gs.element else ElementInfo()
            # An observed pause before this step becomes a Sleep after the
            # previous step (e.g. waiting for a slow screen to load).
            if gs.wait_before > 0 and recorded:
                prev = recorded[-1][1]
                prev.delay_after = max(prev.delay_after, gs.wait_before)

            common = dict(
                element_info=info,
                screen_x=gs.event.x,
                screen_y=gs.event.y,
                locator_override=gs.locator,
                notes=gs.keyword_name,
                window_locator=gs.window_locator,
                anchor_locators=list(gs.anchor_locators),
            )

            typed_into_element = bool(gs.text) and bool(gs.locator) and gs.action in (
                ActionType.SET_VALUE,
                ActionType.TYPE_TEXT,
                ActionType.SELECT,
                ActionType.CLICK,
            )
            if typed_into_element:
                if self._is_dropdown(gs) or gs.action == ActionType.CLICK:
                    # Rule: dropdowns don't accept Set Value/Select - click to
                    # open/focus, then type the value into the same control.
                    _append(gi, RecordedStep(step_number=0, action=ActionType.CLICK, **common))
                _append(
                    gi,
                    RecordedStep(
                        step_number=0,
                        action=ActionType.SEND_KEYS,
                        text_input=gs.text,
                        **common,
                    ),
                )
            else:
                _append(
                    gi,
                    RecordedStep(
                        step_number=0,
                        action=gs.action,
                        text_input=gs.text,
                        **common,
                    ),
                )
        return recorded

    def generate_robot(
        self,
        gen_steps: list[GeneratedStep],
        task_name: str = "AI Generated Task",
        window_locator: str = "",
    ) -> str:
        """Render the final .robot file text."""
        steps = self.to_recorded_steps(gen_steps)
        return generate_robot_file(
            steps,
            task_name=task_name,
            window_locator=window_locator,
        )

    def record_accepted_locators(self, gen_steps: list[GeneratedStep]):
        """Persist chosen locators for future generations (feedback loop)."""
        for gs in gen_steps:
            if gs.element and gs.locator and not gs.error:
                try:
                    self._repo.record_chosen_locator(
                        gs.element.element_id, gs.locator, gs.action.value
                    )
                except Exception:
                    pass
