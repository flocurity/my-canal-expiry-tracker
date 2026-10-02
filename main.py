"""Compatibility launcher: retain checkout-relative data paths."""
from pathlib import Path
from mycanal_hodor_core.console import configure_console
from mycanal_expiry_tracker.cli import main

if __name__ == '__main__':
    configure_console()
    raise SystemExit(main(data_dir=Path(__file__).resolve().parent))
