"""
locator_strategy.py - Locator strategy builder for Robot Framework RPA.Windows.

Analyzes a UIA element's properties and produces a ranked list of
locator strategies, from most reliable to least reliable.

Strategy priority:
    1. AutomationId (most stable across releases)
    2. Name + ControlType (readable but may change with localization)
    3. Path (always works but breaks if tree structure changes)
    4. Combined locators (Name and ControlType and ClassName)
"""

from __future__ import annotations

from src.core.uia_wrapper import ElementInfo


def build_locator_strategies(info: ElementInfo) -> list[dict]:
    """
    Build a ranked list of locator strategies for the given element.

    Each strategy is a dict:
        {
            "type": "AutomationId" | "Name" | "Path" | "Combined" | ...,
            "locator": "the RPA.Windows locator string",
            "reliability": "high" | "medium" | "low",
            "notes": "explanation of trade-offs"
        }

    Returns:
        List of strategy dicts, sorted by reliability (best first).
    """
    strategies = []

    # 1. AutomationId (best when available)
    if info.automation_id:
        strategies.append(
            {
                "type": "AutomationId",
                "locator": f"id:{info.automation_id}",
                "reliability": "high",
                "notes": "Most stable locator. Survives UI layout changes.",
            }
        )

        # AutomationId + Type (even more specific)
        if info.control_type_name:
            strategies.append(
                {
                    "type": "AutomationId+Type",
                    "locator": f"id:{info.automation_id} and type:{info.control_type_name}",
                    "reliability": "high",
                    "notes": "AutomationId scoped to control type. Very reliable.",
                }
            )

    # 2. Name-based locators
    if info.name:
        if info.control_type_name:
            strategies.append(
                {
                    "type": "Name+Type",
                    "locator": f"name:{info.name} and type:{info.control_type_name}",
                    "reliability": "medium",
                    "notes": "Readable but may change with localization or content updates.",
                }
            )
        else:
            strategies.append(
                {
                    "type": "Name",
                    "locator": f"name:{info.name}",
                    "reliability": "medium",
                    "notes": "May match multiple elements. Add type: for specificity.",
                }
            )

    # 3. ClassName + Type
    if info.class_name and info.control_type_name:
        strategies.append(
            {
                "type": "Class+Type",
                "locator": f"class:{info.class_name} and type:{info.control_type_name}",
                "reliability": "medium",
                "notes": "Class names can be generic. Best combined with other locators.",
            }
        )

    # 4. Combined locator (Name + Class + Type)
    if info.name and info.class_name and info.control_type_name:
        strategies.append(
            {
                "type": "Combined",
                "locator": (
                    f"name:{info.name} and class:{info.class_name} "
                    f"and type:{info.control_type_name}"
                ),
                "reliability": "medium",
                "notes": "Very specific but verbose. Good for disambiguating similar elements.",
            }
        )

    # 5. Path (always available as fallback)
    if info.path:
        strategies.append(
            {
                "type": "Path",
                "locator": info.path,
                "reliability": "low",
                "notes": (
                    "Fastest execution but fragile. Breaks if elements are "
                    "added/removed in the tree. Use as last resort."
                ),
            }
        )

    # 6. Desktop > Window > Path (partial path from a named ancestor)
    if info.path and ">" not in info.path:
        # Build a desktop-relative path hint
        strategies.append(
            {
                "type": "Path (from root)",
                "locator": info.path,
                "reliability": "low",
                "notes": "Full path from Desktop root. Fastest but most fragile.",
            }
        )

    # If nothing else, at least give coordinates
    if info.center_x and info.center_y:
        strategies.append(
            {
                "type": "Coordinates",
                "locator": f"coordinates:{info.center_x},{info.center_y}",
                "reliability": "low",
                "notes": (
                    "Click by coordinates. Only use if no other locator works. "
                    "Breaks with resolution/DPI/layout changes."
                ),
            }
        )

    return strategies


def best_locator(info: ElementInfo) -> str:
    """Return the single best locator string for the element."""
    strategies = build_locator_strategies(info)
    if strategies:
        return strategies[0]["locator"]
    return info.path or ""


def locator_for_type(info: ElementInfo, locator_type: str) -> str:
    """Return a specific type of locator (e.g., 'path', 'AutomationId')."""
    strategies = build_locator_strategies(info)
    for s in strategies:
        if s["type"].lower() == locator_type.lower():
            return s["locator"]
    return ""
