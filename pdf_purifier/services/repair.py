"""Repariert Glyphen, die aus dem PDF-Textlayer nicht mehr rekonstruierbar sind.

Warum gibt es überhaupt ``g3C9``?
---------------------------------
Manche PDFs enthalten für Ligaturen (``fl``, ``fi``, ``ff``, ``ffi``) und für
Emoji-Glyphen keinen ``ToUnicode``-Eintrag. Dann ist die Information im
Textlayer verloren, und jeder Extraktor liefert nur einen Platzhalter:

* ``docling-parse`` schreibt ``g`` + Glyph-ID in Hex, z. B. ``g3C9``
* ``pypdfium2`` liefert ``U+FFFE`` (ein Noncharacter)

Gemessen an einem echten Lebenslauf:

=================================  ====================  ============
Roh-Extraktion                     Wahrheit              Ursache
=================================  ====================  ============
``berug3C9iche``                   ``berufliche``        Ligatur ``fl``
``Nikolauspg3C9ege``               ``Nikolauspflege``    Ligatur ``fl``
``(g3C9ießend)``                   ``(fließend)``        Ligatur am Wortanfang
``treg3CAen``                      ``treffen``           Ligatur ``ff``
``Bildung g82F``                   Emoji                 nicht rekonstruierbar
=================================  ====================  ============

Das ist **kein** Problem der KI und auch keines des Chunkings: die Zeichen
fehlen schon vor dem ersten API-Aufruf.

Zwei Fallen, die dieses Modul ausdrücklich behandelt
----------------------------------------------------
1. **Hex-Ziffern sind auch ``a``-``f``.** In ``treg3CAen`` ist der Hex-Lauf
   ``3CAe`` - das letzte ``e`` gehört aber zum Wort (``treffen``). Ein Lauf
   enthält deshalb nur dann einen Platzhalter, wenn mindestens eine *Ziffer*
   vorkommt; das trennt echte Platzhalter von Wörtern wie ``gedacht``
   (``g`` + ``edac``). Zusätzlich wird die Länge des Laufs über die Wortliste
   aufgelöst: es gewinnt die Zerlegung, die ein echtes Wort ergibt.
2. **Platzhalter am Wortanfang/-ende.** ``(g3C9ießend)`` steht zwischen ``(``
   und ``i`` und passt in kein Muster, das einen Buchstaben davor verlangt.
   Deshalb wird hier pro *Token* gearbeitet, nicht per Suchmuster über den
   ganzen Text.

Reparaturstrategie: Ligaturkandidaten werden gegen eine Systemwortliste
geprüft (``/usr/share/dict/...``). Ohne Treffer - etwa bei Eigennamen wie
``Nikolauspflege`` - gewinnt die belegte Glyph-ID bzw. die häufigste Ligatur
``fl``. Ein alleinstehender Platzhalter ist ein Emoji/Symbol; sein Codepoint
lässt sich nicht zurückgewinnen und wird entfernt statt als Müll auszugeben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Platzhalter aus dem Docling-Extraktor: ``g`` + Glyph-ID in Hex.
_RUN = re.compile(r"g([0-9A-Fa-f]{3,5})")
#: Platzhalter aus anderen Extraktoren (pdfium): Noncharacter/Replacement-Char.
_RAW_SENTINELS = re.compile("[\ufffd\ufffe]")
#: Token = alles ohne Leerraum.
_TOKEN = re.compile(r"\S+")

_PUNCTUATION = ".,;:!?()[]{}\"'«»„“‚‘–—-"

#: Mögliche Ligaturen, absteigend nach Häufigkeit im Deutschen/Englischen.
_LIGATURES = ("fl", "fi", "ff", "ffi", "ffl")
_FALLBACK_LIGATURE = "fl"
_MIN_ID_LENGTH = 3
_MAX_ROUNDS = 4

#: Wortlisten für die Kandidatenprüfung.
DICTIONARY_PATHS = (
    "/usr/share/dict/ngerman",
    "/usr/share/dict/ogerman",
    "/usr/share/dict/american-english",
    "/usr/share/dict/words",
)

_dictionary: frozenset[str] | None = None


@dataclass
class RepairReport:
    """Protokoll der durchgeführten Reparaturen."""

    ligatures: dict[str, int] = field(default_factory=dict)
    dropped_symbols: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Anzahl aller ersetzten Platzhalter."""
        return sum(self.ligatures.values()) + self.dropped_symbols

    def print_summary(self) -> None:
        """Gibt eine kurze Zusammenfassung auf der Konsole aus."""
        if self.total == 0:
            return
        print(f"-> {self.total} unlesbare Zeichen aus dem PDF repariert:")
        for ligature, count in sorted(self.ligatures.items()):
            print(f"     {count:>3}x  Ligatur -> {ligature!r}")
        if self.dropped_symbols:
            print(f"     {self.dropped_symbols:>3}x  Emoji/Symbol entfernt (nicht rekonstruierbar)")
        for example in self.examples[:5]:
            print(f"     z. B. {example}")


def _load_dictionary(paths: tuple[str, ...] = DICTIONARY_PATHS) -> frozenset[str]:
    """Lädt die vorhandenen Systemwortlisten (klein geschrieben), gecacht."""
    global _dictionary
    if _dictionary is not None:
        return _dictionary

    words: set[str] = set()
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        words.update(line.strip().lower() for line in text.splitlines() if line.strip())

    _dictionary = frozenset(words)
    return _dictionary


def _looks_like_placeholder(text: str, match: re.Match[str]) -> bool:
    """Unterscheidet ``g3C9`` von harmlosen Buchstabenfolgen wie ``gedacht``.

    ``gedacht`` besteht aus ``g`` + ``edac`` - alles Hex-Ziffern. Echte
    Platzhalter enthalten dagegen mindestens eine Ziffer oder stehen am
    Wortrand (freistehende Symbole).
    """
    digits = match.group(1)
    if any(char.isdigit() for char in digits):
        return True
    following = text[match.end():match.end() + 1]
    return not (following and following.isalpha())


def collect_known_ids(text: str) -> set[str]:
    """Sammelt Glyph-IDs, die keinen Wortbuchstaben mitgeschluckt haben können.

    Endet ein Lauf auf einer Ziffer oder folgt ein Nicht-Buchstabe, ist die
    Länge eindeutig - diese IDs dienen als Beleg für mehrdeutige Stellen.
    """
    known: set[str] = set()
    for match in _RUN.finditer(text):
        digits = match.group(1)
        following = text[match.end():match.end() + 1]
        if digits[-1].isdigit() or not (following and following.isalpha()):
            known.add(digits)
    return known


def _find_placeholder(token: str) -> tuple[int, int, str] | None:
    """Findet den ersten Platzhalter im Token -> (Start, Ende, Hex-Ziffern)."""
    found: tuple[int, int, str] | None = None

    for match in _RUN.finditer(token):
        if _looks_like_placeholder(token, match):
            found = (match.start(), match.end(), match.group(1))
            break

    raw = _RAW_SENTINELS.search(token)
    if raw is not None and (found is None or raw.start() < found[0]):
        found = (raw.start(), raw.end(), "")

    return found


def _preferred_length(known: set[str]) -> int:
    """Häufigste Glyph-ID-Länge im Dokument.

    Bester Anhaltspunkt, wenn weder die Wortliste noch ein Beleg im Dokument
    weiterhilft - etwa bei einem Eigennamen, der nur einmal vorkommt.
    """
    if not known:
        return _MIN_ID_LENGTH
    lengths = [len(entry) for entry in known]
    return max(set(lengths), key=lengths.count)


def _split_order(digits: str, known: set[str]) -> list[int]:
    """Reihenfolge der ID-Längen: belegte zuerst, dann die übliche Länge."""
    if not digits:
        return [0]

    order: list[int] = []

    def remember(length: int) -> None:
        if _MIN_ID_LENGTH <= length <= len(digits) and length not in order:
            order.append(length)

    # 1. Längen, die im Dokument eindeutig belegt sind (Kreuzverweis).
    for length in range(len(digits) - 1, _MIN_ID_LENGTH - 1, -1):
        if digits[:length] in known:
            remember(length)
    # 2. Die im Dokument übliche ID-Länge.
    remember(_preferred_length(known))
    # 3. Der volle Lauf und schließlich alle kürzeren Varianten.
    remember(len(digits))
    for length in range(len(digits) - 1, _MIN_ID_LENGTH - 1, -1):
        remember(length)

    return order


def _lookup_word(candidate: str) -> str:
    """Normalisiert einen Kandidaten für die Wortlistenprüfung."""
    return candidate.strip(_PUNCTUATION).lower()


def _repair_token(
    token: str,
    known: set[str],
    dictionary: frozenset[str],
    report: RepairReport,
) -> str:
    """Repariert alle Platzhalter innerhalb eines Tokens."""
    for _ in range(_MAX_ROUNDS):
        span = _find_placeholder(token)
        if span is None:
            return token

        start, end, digits = span
        prefix, suffix = token[:start], token[end:]

        # Freistehendes Symbol/Emoji: kein Buchstabe, der Kontext liefern könnte.
        if not any(char.isalpha() for char in prefix + suffix):
            report.dropped_symbols += 1
            token = prefix + suffix
            continue

        repaired: str | None = None
        chosen = _FALLBACK_LIGATURE

        # Zerlegung UND Ligatur gemeinsam über die Wortliste auflösen.
        for length in _split_order(digits, known):
            rest = digits[length:]
            for ligature in _LIGATURES:
                candidate = f"{prefix}{ligature}{rest}{suffix}"
                if _lookup_word(candidate) in dictionary:
                    repaired, chosen = candidate, ligature
                    break
            if repaired is not None:
                break

        if repaired is None:
            length = _split_order(digits, known)[0]
            repaired = f"{prefix}{_FALLBACK_LIGATURE}{digits[length:]}{suffix}"

        report.ligatures[chosen] = report.ligatures.get(chosen, 0) + 1
        if len(report.examples) < 5:
            report.examples.append(f"{token!r} -> {repaired!r}")
        token = repaired

    return token


def repair_placeholders(text: str) -> tuple[str, RepairReport]:
    """Ersetzt Platzhalter durch Ligaturen bzw. entfernt nicht rekonstruierbare Symbole.

    Gibt den reparierten Text und ein :class:`RepairReport` zurück.
    """
    report = RepairReport()
    if not _RUN.search(text) and not _RAW_SENTINELS.search(text):
        return text, report

    known = collect_known_ids(text)
    dictionary = _load_dictionary()

    def fix(match: re.Match[str]) -> str:
        return _repair_token(match.group(0), known, dictionary, report)

    return _TOKEN.sub(fix, text), report
