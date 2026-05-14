#!/usr/bin/env python
"""Django CLI entry point."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Run `pip install -e .[dev]` inside an active venv."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
