"""Ermöglicht den Aufruf über ``python -m pdf_purifier``."""

from pdf_purifier.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
