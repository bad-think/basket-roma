"""
_http.py — Helper HTTP condiviso tra tutti i fetcher.

Centralizza:
- User-Agent (per non essere bloccati come bot)
- Timeout uniforme
- Gestione errori HTTP
- Caching minimo in-memory (evita doppie fetch nella stessa run)
"""
from __future__ import annotations

import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

USER_AGENT = (
    "Mozilla/5.0 (compatible; BasketRomaBot/9.0; "
    "+https://github.com/bad-think/basket-roma)"
)
DEFAULT_TIMEOUT = 15.0

# Cache in-memory per evitare doppie fetch nella stessa esecuzione
_CACHE: dict[str, tuple[float, bytes, str]] = {}
_CACHE_TTL_S = 300.0  # 5 minuti


def http_get(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    accept: str = "*/*",
    use_cache: bool = True,
) -> Optional[tuple[bytes, str]]:
    """
    GET HTTP con gestione errori. Ritorna (body, content_type) o None su errore.

    Args:
        url: URL completo da scaricare
        timeout: secondi prima di abortire
        accept: header Accept (es. "application/rss+xml" per RSS)
        use_cache: se True, riusa risultato cachato per 5 minuti

    Returns:
        Tuple (body_bytes, content_type) o None su errore (qualsiasi: rete,
        HTTP 4xx/5xx, timeout). Stampa warning su stderr per debug.
    """
    now = time.time()
    if use_cache and url in _CACHE:
        ts, body, ct = _CACHE[url]
        if (now - ts) < _CACHE_TTL_S:
            return body, ct

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ct = resp.headers.get("Content-Type", "")
        if use_cache:
            _CACHE[url] = (now, body, ct)
        return body, ct
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  HTTP {e.code} su {url}")
        return None
    except urllib.error.URLError as e:
        print(f"  ⚠️  URLError su {url}: {e.reason}")
        return None
    except Exception as e:
        print(f"  ⚠️  Errore su {url}: {type(e).__name__}: {e}")
        return None


def http_get_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[str]:
    """Variante che decodifica come testo UTF-8 con fallback latin-1."""
    res = http_get(url, timeout=timeout)
    if res is None:
        return None
    body, _ = res
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return body.decode("latin-1")
        except Exception:
            return None


def clear_cache() -> None:
    """Pulisce la cache (per test)."""
    _CACHE.clear()
