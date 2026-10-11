"""Reine Logik ohne Home-Assistant-Abhaengigkeit (leicht testbar)."""
from __future__ import annotations

import re
from datetime import datetime

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})

_TOKENS = (
    ("%CCYY", "%Y"),
    ("%YY", "%y"),
    ("%MM", "%m"),
    ("%DD", "%d"),
    ("%hh", "%H"),
    ("%mm", "%M"),
    ("%ss", "%S"),
)


def norm(text: str) -> str:
    """Name zum Vergleichen: klein, Umlaute aufgeloest, nur Buchstaben/Ziffern."""
    return re.sub(r"[^a-z0-9]", "", str(text).translate(_UMLAUTE).lower())


def render_tokens(text: str, when: datetime) -> str:
    """Datums-Platzhalter (%DD.%MM.%CCYY ...) in echte Werte umsetzen."""
    for token, fmt in _TOKENS:
        text = text.replace(token, when.strftime(fmt))
    return text


def split_path(text: str) -> list[str]:
    """'Der_Fuchsbau/bei Nacht' -> ['Der_Fuchsbau', 'bei Nacht'] (leere Teile und '..' fallen weg)."""
    return [p.strip() for p in re.split(r"[/\\]", text or "") if p.strip() and p.strip() not in (".", "..")]


def render_pattern(pattern: str, when: datetime, *, cam: str, kuerzel: str, profil: str) -> str:
    """Dateimuster eines Profils: {cam} {kuerzel} {profil} plus Datums-Platzhalter."""
    text = pattern.replace("{cam}", cam).replace("{kuerzel}", kuerzel).replace("{profil}", profil)
    return render_tokens(text, when)


def in_time_window(now: datetime, start: str | None, end: str | None) -> bool:
    """Liegt now im Fenster start..end ('HH:MM[:SS]')? Fenster ueber Mitternacht sind erlaubt."""
    if not start or not end:
        return True
    cur = now.strftime("%H:%M:%S")
    s, e = (start + ":00")[:8] if len(start) == 5 else start, (end + ":00")[:8] if len(end) == 5 else end
    if s == e:
        return True
    return s <= cur < e if s < e else (cur >= s or cur < e)
