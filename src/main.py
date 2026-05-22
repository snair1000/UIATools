"""
UIATools - UI Automation Element Inspector
Entry point: launches the tkinter-based inspector GUI.
Run with: python -m src.main
"""

import sys
import ctypes


def main():
    """Launch the UIATools Inspector GUI."""
    # Ensure we're running on Windows
    if sys.platform != "win32":
        print("ERROR: UIATools only runs on Windows.")
        sys.exit(1)

    # Set DPI awareness for accurate coordinate mapping
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    from src.gui.inspector_app import InspectorApp

    app = InspectorApp()
    app.run()


if __name__ == "__main__":
    main()
