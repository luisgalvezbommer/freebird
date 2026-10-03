"""Regressionstest für die Entfernung personalisierter Kopie-Kennzeichnungen.

Warum dieser Test existiert
---------------------------
Die erste Fassung von ``redact.py`` hat auf allgemeine Wörter
("Bestellnummer", "Lizenz für") und auf **jede** E-Mail-Adresse reagiert.
In einem Lehrbuch mit Beispiel-E-Mails und Beispiel-Datensätzen hat das
echten Lehrinhalt gelöscht - in sechs Blöcken des IT-Handbuchs.

Dieser Test hält beide Richtungen fest:

* Die echte Kennzeichnung **muss** verschwinden (inkl. Fortsetzungszeile).
* Die Lehrbuch-Beispiele **müssen** erhalten bleiben.
* Ein Ankerwort ohne Identitätsmerkmal darf **nicht** löschen, nur melden.

Aufruf::

    .venv/bin/python tests/test_redact.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_purifier.services.redact import redact_personal_data  # noqa: E402

# Die echte Kennzeichnung aus dem IT-Handbuch (Absatz, 2 Zeilen).
ECHTE_KENNZEICHNUNG = """# Kapitel 1

Exemplar Nr. jg3b-5ytq-eu6i-axr4 zum persönlichen Gebrauch für Manuel Arturo
Galvez Estrada, gal531026@hotmail.com

Der Rechner besteht aus Eingabe, Verarbeitung und Ausgabe.
"""

# Zeilen, die in einem Lehrbuch vorkommen und NICHT gelöscht werden dürfen.
# Jede Zeile hier wurde von der fehlerhaften ersten Fassung tatsächlich
# gelöscht - inklusive dem Block, in dem sie auftrat.
LEHRINHALT = (
    # Block 3: telnet-Beispiel
    "# telnet pop.myprovider.de pop3 +OK POP3 server ready USER absender +OK PASS XXXXX",
    # Block 3: Beispiel-Mail-Header
    "for absender@myprovider.de; Sat, 24 Apr 2021 03:08:18 +0100 Received: from box",
    # Block 3: Satz über Windows-Lizenzen
    "- L50776 Windows 10 Education bietet alle Funktionen der Enterprise-Version,",
    # Block 4: Beispiel-Datensatz mit Telefonnummer
    "Müller, Anna; E-Mail: anna.mueller@example.com; Telefon: 0161/12345678",
    # Block 6: Stammdaten-Erklärung (enthält "Bestellnummer")
    "- L50776 Stammdatum und Ordnungsdatum sind etwa der Name einer Person, die",
    # Block 6: JSON-Beispielsatz aus der Datenbank
    '{ "_id": "8e31cf918831d547d77845b157003823", "lastname": "Müller", "email": "angelika@example.com" }',
    # Normale Erwähnung von "persönlich"
    "Personenbezogene Daten sind alle Informationen über eine betroffene Person.",
    # Persönliches Exemplar als Fließtext im Impressum eines anderen Verlags
    "Der Verlag behält sich das Recht vor, diese Software zu lizenzieren.",
)


def _run() -> int:
    fehler = 0

    # --- Richtung 1: Die echte Kennzeichnung muss weg -------------------
    ergebnis = redact_personal_data(ECHTE_KENNZEICHNUNG)
    for verboten in ("Galvez", "gal531026", "Exemplar Nr", "persönlichen Gebrauch"):
        if verboten in ergebnis.text:
            print(f"FEHLER  Kennzeichnung nicht entfernt: {verboten!r}")
            fehler += 1
    if len(ergebnis.removed) != 2:
        print(f"FEHLER  erwartet 2 entfernte Zeilen, waren {len(ergebnis.removed)}")
        fehler += 1
    for muss_bleiben in ("# Kapitel 1", "Der Rechner besteht aus Eingabe"):
        if muss_bleiben not in ergebnis.text:
            print(f"FEHLER  Nachbartext mitgelöscht: {muss_bleiben!r}")
            fehler += 1

    # --- Richtung 2: Lehrinhalt muss erhalten bleiben -------------------
    for zeile in LEHRINHALT:
        ergebnis = redact_personal_data(f"# Kapitel\n\n{zeile}\n\nText danach.\n")
        if zeile not in ergebnis.text:
            print(f"FEHLER  Lehrinhalt gelöscht: {zeile[:70]!r}")
            print(f"        entfernt wurde: {ergebnis.removed!r}")
            fehler += 1

    # --- Richtung 3: Sicherheitsbremse bei langen Absätzen --------------
    # Ein 10-zeiliger Absatz mit Ankerwort darf nicht komplett verschwinden.
    langer_absatz = "\n".join(["Dies ist ein sehr langer Absatz."] * 9)
    langer_absatz += "\nExemplar Nr. 123 zum persönlichen Gebrauch für Max Muster, m@example.com"
    ergebnis = redact_personal_data(f"{langer_absatz}\n")
    if "sehr langer Absatz" not in ergebnis.text:
        print("FEHLER  Sicherheitsbremse: langer Absatz wurde mitgelöscht")
        fehler += 1
    if not ergebnis.removed:
        print("FEHLER  Ankerzeile im langen Absatz wurde nicht entfernt")
        fehler += 1

    # --- Richtung 4: Ankerwort ohne Identitätsmerkmal bleibt stehen -----
    # "nur zum persönlichen Gebrauch" im Urheberrechtshinweis darf NICHT
    # gelöscht werden - muss aber zur Prüfung gemeldet werden.
    urheberrecht = (
        "Dieses E-Book ist urheberrechtlich geschützt. Sie dürfen es ausdrucken,\n"
        "aber auch dies nur zum persönlichen Gebrauch. Die Weitergabe an Dritte\n"
        "ist nicht erlaubt.\n"
    )
    ergebnis = redact_personal_data(urheberrecht)
    if "urheberrechtlich geschützt" not in ergebnis.text:
        print("FEHLER  Urheberrechtshinweis wurde gelöscht")
        fehler += 1
    if not ergebnis.review:
        print("FEHLER  Urheberrechtshinweis wurde nicht zur Prüfung gemeldet")
        fehler += 1

    if fehler == 0:
        print(f"OK - {len(LEHRINHALT)} Lehrinhalt-Zeilen erhalten, Kennzeichnung entfernt,")
        print("     Sicherheitsbremse und Prüf-Meldung greifen.")
    else:
        print(f"{fehler} Fehler.")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(_run())
