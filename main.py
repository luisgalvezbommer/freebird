"""Einstiegspunkt für ``python main.py``.

Die eigentliche Logik liegt im Package :mod:`pdf_purifier`. Diese Datei bleibt
als bequemer Launcher erhalten, damit der bisherige Aufruf weiter funktioniert.
"""

from pdf_purifier.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
