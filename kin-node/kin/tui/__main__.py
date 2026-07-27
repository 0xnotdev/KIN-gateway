"""Module entry point for KIN TUI: `python -m kin.tui`."""

import sys
from kin.tui.app import run_tui_app

def main() -> None:
    sys.exit(run_tui_app())

if __name__ == "__main__":
    main()
