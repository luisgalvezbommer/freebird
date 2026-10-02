"""Schritt 0: Prüft vor dem Start, ob die nötigen System-Tools vorhanden sind."""

from __future__ import annotations

import shutil
import sys

# Anzeigename je ausführbarer Datei (Binary).
_TOOL_LABELS = {
    "pandoc": "Pandoc",
    "weasyprint": "WeasyPrint",
}


def missing_tools(pdf_engine: str = "weasyprint") -> list[str]:
    """Gibt die Binaries zurück, die im ``PATH`` fehlen (ohne Duplikate)."""
    required = ["pandoc", pdf_engine]
    return [tool for tool in dict.fromkeys(required) if shutil.which(tool) is None]


def check_system_dependencies(pdf_engine: str = "weasyprint") -> None:
    """Bricht mit Hilfetext ab, wenn benötigte System-Tools fehlen."""
    print("[0/4] Führe System-Pre-Flight-Check durch...")

    missing = missing_tools(pdf_engine)
    if not missing:
        print("-> Alle System-Tools gefunden. Start frei!\n")
        return

    labels = [_TOOL_LABELS.get(tool, tool) for tool in missing]

    print("\n" + "!" * 60)
    print("FEHLENDE SYSTEM-SOFTWARE ERKANNT!")
    print("!" * 60)
    print("Für die PDF-Konvertierung werden externe Tools benötigt.")
    print(f"Folgende Software fehlt auf deinem PC: {', '.join(labels)}\n")
    print("Bitte installiere die fehlenden Tools wie folgt:")

    # Plattform-spezifische Installationshinweise ausgeben
    if sys.platform == "win32":
        print(" -> Windows (Terminal/PowerShell öffnen und eingeben):")
        if "Pandoc" in labels:
            print("    winget install JohnMacFarlane.Pandoc")
        if "weasyprint" in labels:
            print("    pip install weasyprint")
    elif sys.platform == "darwin":
        print(" -> macOS (Terminal öffnen und eingeben):")
        print(f"    brew install {' '.join(missing)}")
    else:
        print(" -> Linux (Ubuntu/Debian Terminal öffnen und eingeben):")
        print(f"    sudo apt update && sudo apt install {' '.join(missing)}")

    print("\nStarte das Skript nach der Installation einfach erneut.")
    print("!" * 60 + "\n")
    sys.exit(1)
