# UIATools - UI Automation Element Inspector

A Windows desktop tool to **accelerate migration from WinAppDriver to Robot Framework's RPA.Windows library**. It identifies UI elements by their screen coordinates, bounding rectangles, and tree paths (`path:1|12|1|2|1`), then exports ready-to-use RPA.Windows locator strategies — and can **record full click sequences** into `.robot` files.

## Why This Tool?

When migrating from WinAppDriver (XPath-based) to RPA.Windows:
- Existing XPath locators often don't translate directly
- Manual element inspection with Inspect.exe / WinAppDriver Recorder is slow
- `path:`-based locators in RPA.Windows are fastest but hard to discover manually
- This tool **automates the discovery** of paths, coordinates, and properties in one click
- The built-in **recorder** captures interactions and generates Robot Framework code automatically

## Features

| Feature | Description |
|---|---|
| **Click-to-Inspect** | Ctrl+I to enter inspect mode, then click any element on screen |
| **Tree View** | Full UIA element hierarchy with search/filter |
| **Path Builder** | Automatic `path:1\|3\|2\|1` computation matching RPA.Windows format |
| **Coordinate Mapping** | Maps (x, y) → element → path → bounding rectangle |
| **Path Resolution** | Enter a path → navigate to element → verify it exists |
| **Property Inspector** | All UIA properties: Name, AutomationId, ClassName, ControlType, Value, etc. |
| **Locator Strategies** | Ranked locators: AutomationId > Name+Type > Path > Coordinates |
| **RF Export** | One-click copy of `Get Element` keywords and variable definitions |
| **Bulk Export** | Export entire tree to `.robot` file with variables and comments |
| **Element Highlight** | Red overlay rectangle showing the selected element on screen |
| **Recorder** | Record click sequences and generate complete `.robot` files with reusable keywords |
| **Playback** | Run recorded steps directly to test/verify automation flows before export |
| **Compact Mode** | Smaller window showing only key locators + recorder for side-by-side work |

## Quick Start

### Prerequisites
- **Windows 10/11** (required — uses Windows UI Automation)
- **Python 3.10+** (only if running from source)

### Option A — Use the Standalone Executable (Recommended)

The easiest way to use UIATools is with the pre-built executable:

1. Download `UIATools.exe` from the `dist/` folder (or releases).
2. Run `UIATools.exe` — no Python installation required!

> **Note:** The executable is a portable, single-file application. You may need to allow it through Windows SmartScreen on first launch.

### Option B — Run from Source

```bash
# Clone or download the project
cd UIATools

# Create and activate a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run the Inspector (from source)

```bash
python -m src.main
```

The tool launches in **Full Mode** (1280×800) with the tree panel on the left and the inspector/recorder tabs on the right.

---

## Step-by-Step Usage Guide

### Step 1 — Launch the tool

```bash
cd UIATools
.venv\Scripts\activate
python -m src.main
```

You will see the main window with:
- A **toolbar** across the top (Select Window, Refresh, Inspect, Record, Compact, path lookup, depth control)
- A **tree panel** on the left (empty until you select a window)
- A **tabbed panel** on the right with two tabs: **🔍 Inspector** and **⏺ Recorder**
- A **status bar** at the bottom

### Step 2 — Select a target application

1. Open the application you want to inspect (e.g. Notepad, Calculator, your own desktop app).
2. In UIATools, click **📋 Select Window** in the toolbar.
3. A dialog lists all visible top-level windows — select yours and click **Select**.
4. The UIA element tree loads automatically in the left panel. The first two levels are expanded by default.

> **Tip:** Reduce **Max Depth** (default 8) in the toolbar before loading if the app has a very deep tree (e.g. WebView2 / Chromium-based apps). This speeds up loading significantly.

### Step 3 — Inspect elements

You have three ways to inspect elements:

#### Option A — Click-to-Inspect mode (recommended)
1. Press **Ctrl+I** or click **🎯 Click-to-Inspect** in the toolbar.
2. The status bar reads: *"INSPECT MODE: Hold Ctrl and click on any element to inspect it."*
3. Move to the target application and **Ctrl+click** on any UI element.
4. The tool instantly shows:
   - The element highlighted with a **red overlay rectangle** on screen
   - **Quick Info** in the Inspector tab: Path, Name, AutomationId, ClassName, Type, Value, BoundingRect, Center coordinates
   - **All Properties** table with every UIA property
   - **Robot Framework Export** section with ranked locator strategies and a ready-to-copy keyword
5. The element is also selected in the tree panel (if the tree is loaded).
6. Press **Esc** or click the button again to stop inspect mode.

#### Option B — Select from the tree
1. After loading a window tree (Step 2), expand nodes in the tree panel.
2. Click any element — its properties appear in the Inspector tab and the element highlights on screen.
3. Use the **Filter** search box at the top of the tree panel to narrow results by name, AutomationId, class, or type.

#### Option C — Inspect at cursor
1. Hover your mouse over the target element in the application.
2. Click **📍 Inspect at Cursor** in the toolbar (or use the **Inspect → Inspect at Cursor** menu).
3. The element under the current cursor position is inspected.

### Step 4 — Copy locators for Robot Framework

Once an element is inspected, you can copy its locator in several ways:

| Action | How |
|---|---|
| Copy the path locator | Click **Copy Path** in the Quick Info header, or **Export → Copy RF Locator (Path)** |
| Copy the best locator | **Export → Copy RF Locator (Best)** — picks AutomationId if available, then Name+Type, then path |
| Copy a full RF keyword | **Export → Copy RF Keyword** — e.g. `${element}=    Get Element    id:btnSave` |
| Copy AutomationId | Click **Copy AutomationId** in the Quick Info header |
| Copy Name | Click **Copy Name** in the Quick Info header |
| Copy all properties | Click **Copy All** — copies every property as text |
| View all strategies | **Export → Export Locator Strategies** — opens a dialog ranking every possible locator |

> **Tip:** Double-click any row in the **All Properties** table to copy that value to the clipboard.

### Step 5 — Verify a path from an existing script

If you have a path like `path:1|3|2|1` in a Robot Framework script and want to check what element it points to:

1. Type the path into the **Path** field in the toolbar (with or without the `path:` prefix).
2. Click **Go** or press **Enter**.
3. The element resolves, highlights on screen, and its properties appear in the Inspector tab.

Alternatively, use **Ctrl+L** to open the path lookup dialog.

### Step 6 — Record a click sequence

The Recorder captures user interactions and generates complete `.robot` files.

1. Press **Ctrl+R** or click **⏺ Record** in the toolbar.
2. The status bar reads: *"RECORDING: Hold Ctrl and click elements to record steps."*
3. The Recorder tab opens automatically.
4. **Ctrl+click** elements in your target application — each click is recorded as a step with its element info and best locator.
5. **Ctrl+right-click** to record right-click actions.
6. Press **Ctrl+R** again to **stop recording**.

Each recorded step shows: step number, action type, element name, locator, and text input.

### Step 7 — Edit recorded steps

After recording, you can fine-tune steps in the Recorder tab:

| Action | Button / How |
|---|---|
| **Reorder steps** | Select a step, click **⬆** or **⬇** |
| **Delete a step** | Select a step, click **❌ Delete** |
| **Change action type** | Select a step, click **✏ Change Action** — choose from Click, Right Click, Double Click, Type Text, Set Value, Select, Get Element, Wait For Element |
| **Set text input** | Select a step, click **📝 Set Text** — enter the text for Type Text / Set Value actions |
| **Override locator** | Select a step, click **🔗 Override Locator** — pick from ranked strategies or enter a custom locator |
| **Set wait timing** | Select a step, click **⏱ Set Wait** — configure wait-for-ready and wait-after-action timing |
| **Add Type Text** | Select a step, click **➕ Add Type Text** — inserts a Type Text step after the selected one using the same element |
| **Add Wait** | Select a step, click **➕ Add Wait** — inserts a Wait For Element step after the selected one |

> **Tip:** Click any step in the list to highlight the corresponding element on screen and view its properties in the Inspector tab.

### Step 8 — Run recorded steps (Playback)

Before generating Robot Framework code, you can test your recorded steps directly in the tool:

1. After recording and editing your steps, click **▶ Run All** in the Recorder tab (or press **Ctrl+P**).
2. The tool executes each step in sequence, showing status in the **Status** column:
   - **✓ OK** — step executed successfully
   - **✗ Error** — step failed (shows brief error message)
   - **Skipped** — step was disabled
3. Watch the playback to verify your automation works as expected.

#### Playback controls

| Control | Action |
|---|---|
| **▶ Run All** | Execute all recorded steps from the beginning |
| **⏭ Step** | Execute only the selected step (or next step if paused) |
| **⏸ Pause** | Pause execution after the current step completes |
| **⏹ Stop** | Stop execution immediately |
| **Delay** | Set delay between steps (default: 0.5 seconds) |
| **Wait for ready** | When checked, waits for element to be visible and enabled before each action |
| **Wait after** | Seconds to wait after each action for UI to settle (default: 0.3s) |

#### Per-step wait settings

For fine-grained control, you can set wait behavior per step:

1. Select a step in the list.
2. Click **⏱ Set Wait** in the editing buttons.
3. Configure:
   - **Wait for element to be visible and clickable** — waits before action
   - **Wait after action completes** — additional delay for UI to settle
4. Optionally check **Apply to all recorded steps** to set the same values for all steps.

> **Tip:** Use **⏭ Step** (or press **F9**) to execute steps one at a time for debugging. This helps identify which step fails and why.

> **Tip:** If a step fails due to a timing issue, enable **Wait for ready** or increase **Wait after** for that step.

### Step 9 — Generate Robot Framework code

Once your steps are ready:

1. Click **📄 Generate .robot** in the Recorder tab.
2. A dialog lets you configure:
   - **Task Name** — the name of the generated `*** Tasks ***` entry
   - **Window Locator** — optional; adds a `Control Window` call at the top
   - **Use locator variables** — creates `*** Variables ***` section with `${LOCATOR_...}` variables
   - **Include comments** — adds element metadata as comments
   - **Include recorded delays** — inserts `Sleep` calls between steps
   - **Generate reusable keyword** — wraps steps in a `*** Keywords ***` block
3. Click **Generate** — the complete `.robot` file opens in a preview window.
4. From the preview you can **Copy All** to clipboard or close.

#### Save directly to a file
- Click **💾 Save .robot** instead — same options dialog, then choose a save location.

#### Copy keyword only
- Click **📋 Copy Keyword** — copies just the keyword block (no Settings/Variables/Tasks) to clipboard.

### Step 10 — Bulk export the entire tree

To export locator information for every element in the loaded tree:

1. Load a window tree (Step 2).
2. Go to **File → Export All to File**.
3. Choose a save location (`.robot`, `.txt`, or `.csv`).
4. The file contains a locator entry for every element in the tree.

### Step 11 — Use Compact Mode for side-by-side work

When inspecting elements you often need to see the target application alongside the tool. Compact Mode shrinks the window and shows only what matters.

1. Press **Ctrl+M** or click **📐 Compact** in the toolbar (or use **View → Toggle Compact Mode**).
2. The window shrinks to **620×520** and shows:
   - **Core toolbar:** Select Window, Refresh, Inspect, Record, Compact toggle
   - **Quick Info locators:** Path, Name, AutomationId, ClassName, Type, Value, BoundingRect, Center
   - **Recorder tab:** fully functional with all recording and editing controls
3. Hidden in compact mode: tree panel, All Properties table, RF Export section, path lookup, depth control.
4. Press **Ctrl+M** again to return to **Full Mode** (1280×800) with all panels restored.

> **Tip:** Compact Mode is ideal for recording workflows — keep the tool docked to one side of the screen and your target application on the other.

---

## Locator Strategy Priority

The tool recommends locators in this order:

| Priority | Type | Example | Reliability |
|---|---|---|---|
| 1 | AutomationId | `id:btnSave` | ⭐⭐⭐ High |
| 2 | AutomationId+Type | `id:btnSave and type:Button` | ⭐⭐⭐ High |
| 3 | Name+Type | `name:Save and type:Button` | ⭐⭐ Medium |
| 4 | Class+Type | `class:Button and type:Button` | ⭐⭐ Medium |
| 5 | Combined | `name:Save and class:Button and type:Button` | ⭐⭐ Medium |
| 6 | Path | `path:1\|3\|2\|1` | ⭐ Low (fastest) |
| 7 | Coordinates | `coordinates:500,300` | ⭐ Low (fragile) |

> **Tip:** Path locators are the **fastest** for execution but **break** if the UI tree structure changes. Use AutomationId when available.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+I` | Toggle click-to-inspect mode |
| `Ctrl+R` | Toggle recording mode |
| `Ctrl+P` | Run all recorded steps |
| `F9` | Run single step |
| `Ctrl+M` | Toggle compact / full mode |
| `Ctrl+L` | Open path lookup dialog |
| `F5` | Refresh the element tree |
| `Esc` | Stop all active modes (inspect + record + playback) |

## Project Structure

```
UIATools/
├── src/
│   ├── main.py                  # Entry point
│   ├── core/
│   │   ├── uia_wrapper.py       # Low-level UIA COM wrapper + ElementInfo dataclass
│   │   ├── tree_walker.py       # Walks UIA tree, builds paths
│   │   ├── element_inspector.py # Deep element property inspection
│   │   ├── coord_mapper.py      # Maps (x,y) ↔ elements ↔ paths
│   │   ├── recorder.py          # Records click sequences as steps
│   │   └── step_executor.py     # Executes recorded steps for playback
│   ├── gui/
│   │   ├── inspector_app.py     # Main tkinter application + compact mode
│   │   ├── tree_panel.py        # Tree view with search/filter
│   │   ├── property_panel.py    # Property display + compact mode support
│   │   ├── recorder_panel.py    # Recorder controls, step list, editing, playback
│   │   └── highlight.py         # Red overlay rectangle
│   ├── export/
│   │   ├── rf_exporter.py       # Robot Framework keyword/variable export
│   │   ├── rf_code_generator.py # Full .robot file generator from recorded steps
│   │   └── locator_strategy.py  # Ranked locator builder
│   └── utils/
│       ├── mouse_hook.py        # Global mouse hook (click-to-inspect / record)
│       └── win_helpers.py       # Windows API helpers
├── dist/
│   └── UIATools.exe             # Pre-built standalone executable
├── build.bat                    # Build script for creating the executable
├── UIATools.spec                # PyInstaller configuration
├── tests/
├── requirements.txt
└── README.md
```

## Dependencies

| Package | Purpose |
|---|---|
| `uiautomation` | Core Windows UI Automation access |
| `pywinauto` | Complementary UIA + Win32 access |
| `comtypes` | COM interface support |
| `pywin32` | Windows API bindings |
| `Pillow` | Image capture support |
| `pyinstaller` | Building standalone executable (optional) |

## Building from Source

To build a standalone executable from source:

### Quick Build (Windows)

```bash
# Run the build script
build.bat
```

The executable will be created at `dist/UIATools.exe`.

### Manual Build

```bash
# Activate virtual environment
.venv\Scripts\activate

# Install PyInstaller if not already installed
pip install pyinstaller>=6.0.0

# Build using the spec file
pyinstaller UIATools.spec --clean
```

### Build Output

| File | Description |
|---|---|
| `dist/UIATools.exe` | Standalone executable (no Python required) |
| `build/` | Intermediate build files (can be deleted) |

> **Tip:** The executable bundles all dependencies and runs without any external installations. It's ideal for distribution to team members who don't have Python set up.

## Troubleshooting

### "No element found at (x, y)"
- Ensure the target app is **visible and not minimized**
- Check DPI scaling — the tool sets DPI awareness at startup, but multi-monitor setups with mixed scaling can cause offsets
- Some embedded web content (WebView2) may not expose UIA elements at all depths
- Run the tool as **Administrator** if the target app is elevated

### Tree is slow to load
- Reduce **Max Depth** in the toolbar (default: 8) before loading
- Select a **specific window** instead of the Desktop root
- Complex apps with Chromium / WebView2 content may have tens of thousands of nodes — use depth 3–5 for those

### Path doesn't resolve
- Paths are **position-dependent**: if a sibling element was added/removed (e.g. a dynamic list), paths shift
- Use **Refresh (F5)** to rebuild the tree and get updated paths
- For dynamic UIs, prefer AutomationId or Name+Type locators over path

### Inspect mode doesn't capture clicks
- Make sure to **hold Ctrl** when clicking — unmodified clicks pass through to the target app
- The global mouse hook requires the tool window to be running — don't minimize it
- If hooks stop working, press **Esc** and re-enable with **Ctrl+I**

### Generated .robot file has wrong locators
- Select a step in the Recorder tab and click **🔗 Override Locator** to manually choose a better strategy
- Double-check that the AutomationId is unique — use **AutomationId+Type** for disambiguation
- Re-inspect the element after UI changes with **Ctrl+I** to get fresh properties

## License

Internal tool for migration project.
