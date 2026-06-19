# UIATools - UI Automation Element Inspector

## Project Overview
A Python-based UI Automation element inspector tool designed to accelerate migration from WinAppDriver to Robot Framework's RPA.Windows library. The tool identifies UI elements by their coordinates, bounding rectangles, and tree paths (e.g., `path:1|12|1|2|1`).

## Tech Stack
- **Language:** Python 3.10+
- **UI Automation:** uiautomation, pywinauto, comtypes
- **GUI:** tkinter (built-in)
- **Target Integration:** Robot Framework + RPA.Windows library
- **Platform:** Windows only

## Project Structure
```
UIATools/
├── src/
│   ├── __init__.py
│   ├── main.py                  # Entry point - launches the GUI
│   ├── core/
│   │   ├── __init__.py
│   │   ├── tree_walker.py       # Walks UIA tree, builds paths
│   │   ├── element_inspector.py # Inspects element properties
│   │   ├── coord_mapper.py      # Maps x,y to elements and paths
│   │   ├── uia_wrapper.py       # Low-level UIA COM wrapper
│   │   ├── recorder.py          # Records click sequences as steps
│   │   └── step_executor.py     # Executes recorded steps for playback
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── inspector_app.py     # Main tkinter application
│   │   ├── tree_panel.py        # Tree view panel
│   │   ├── property_panel.py    # Element property display
│   │   ├── recorder_panel.py    # Recorder controls, step list, playback
│   │   └── highlight.py         # Element highlight overlay
│   ├── export/
│   │   ├── __init__.py
│   │   ├── rf_exporter.py       # Robot Framework locator export
│   │   ├── rf_code_generator.py # Full .robot file generator
│   │   └── locator_strategy.py  # Locator strategy builder
│   └── utils/
│       ├── __init__.py
│       ├── mouse_hook.py        # Global mouse hook for click-to-inspect
│       └── win_helpers.py       # Windows API helpers
├── tests/
│   └── __init__.py
├── requirements.txt
├── README.md
└── .github/
    └── copilot-instructions.md
```

## Key Conventions
- All UIA element paths use 1-based indexing matching RPA.Windows format: `path:1|12|1|2|1`
- Locator strategies prioritize: AutomationId > Name > path (for reliability vs speed tradeoff)
- The tool always captures: element path, bounding rect, center x/y, all UIA properties
- Export format targets Robot Framework RPA.Windows `Control Window` / `Get Element` syntax

## Development
- Run with: `python -m src.main`
- Install deps: `pip install -r requirements.txt`
- Python 3.10+ required on Windows
