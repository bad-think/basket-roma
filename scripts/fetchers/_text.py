"""
_text.py — Utility testo condivise tra fetcher.

Normalizzazione nomi squadra: fondamentale per matchare la stessa squadra
con varianti diverse (es. "Virtus GVM Roma 1960" vs "Virtus Roma" vs "VIRTUS GVM").
"""
from __future__ import annotations

import re
import unicodedata


def normalize(s: str) -> str:
    """
    Normalizza una stringa per confronto: lower, no accenti, spazi compatti.

    >>> normalize("Virtus GVM Roma 1960")
    'virtus gvm roma 1960'
    >>> normalize("OraSì Ravenna")
    'orasi ravenna'
    """
    if not s:
        return ""
    # Rimuove accenti
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lower + spazi compatti
    s = " ".join(s.lower().strip().split())
    return s


def team_name_matches(candidate: str, aliases: list[str]) -> bool:
    """
    True se `candidate` corrisponde a una delle aliases (match parziale entrambi i versi).

    Esempi:
        team_name_matches("Virtus Roma", ["virtus gvm roma 1960"]) → True
        team_name_matches("Logiman Orzinuovi", ["orzinuovi"]) → True
    """
    cn = normalize(candidate)
    if not cn:
        return False
    for a in aliases:
        an = normalize(a)
        if not an:
            continue
        if cn == an:
            return True
        if cn in an or an in cn:
            return True
    return False


# Pattern comune per estrarre score da testo libero: "82-74", "82 - 74", "82–74"
SCORE_PATTERN = re.compile(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b")


def extract_scores(text: str) -> list[tuple[int, int]]:
    """Estrae tutti i pattern di score da un testo."""
    out = []
    for m in SCORE_PATTERN.finditer(text):
        try:
            sh = int(m.group(1))
            sa = int(m.group(2))
            # Filtra score irragionevoli
            if 30 <= sh <= 200 and 30 <= sa <= 200:
                out.append((sh, sa))
        except ValueError:
            continue
    return out


def strip_html(html: str) -> str:
    """Rimuove tag HTML basilarmente per parsing testo."""
    if not html:
        return ""
    # Rimuovi script e style con contenuti
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Rimuovi tag
    html = re.sub(r"<[^>]+>", " ", html)
    # Decodifica entità HTML basilari
    html = (html.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&#039;", "'")
                .replace("&nbsp;", " "))
    # Compatta whitespace
    return re.sub(r"\s+", " ", html).strip()
