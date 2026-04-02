#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v5
Ottimizzato per girare in < 3 minuti.

Strategia:
- Timeout aggressivo (5s per URL)
- Max 3 URL per giornata da provare
- Priorità agli URL noti verificati
- Fonti: pianetabasket (principale), Sofascore (orari), siti squadre
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================
CONFIG = {
    "season": "2025-26",
    "next_season": "2026-27",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": [
                "virtus gvm roma", "virtus roma", "virtus gvm roma 1960",
                "pallacanestro virtus roma"
            ],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basketball"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        }
    }
}

# ================================================================
# URL VERIFICATI — aggiornati man mano che le giornate vengono giocate
# ================================================================
KNOWN_URLS = {
    31: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-le-gare-di-lunedi-classifiche-31-giornata-2025-26-356237",
    32: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-32-giornata-2025-26-357140",
    33: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-33-giornata-2025-26-357782",
    # 34-38: trovati automaticamente dalla homepage o dalla stima
}

# ID base stimati — G33=357782, incremento reale G32→G33 = 642
# Usiamo 642 come incremento reale invece di 1500
ROUND_BASE_IDS = {
    34: 358424, 35: 359066, 36: 359708,
    37: 360350, 38: 360992,
}

# Suffissi da provare — solo i più comuni per limitare le richieste
URL_SUFFIXES_FAST = [
    "classifiche",
    "sabato-classifiche",
    "domenica-classifiche",
    "le-gare-di-lunedi-classifiche",
]

LEAGUE_SOURCES = {
    "B Nazionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
        "pb_class":     "https://www.pianetabasket.com/serie-b/classifica-serie-b-nazionale-girone-b-2025-26",
        "pb_rss":       "https://www.pianetabasket.com/feed/serie-b/",
        "playbasket":   "https://www.playbasket.it/serie-b",
        "lnp":          "https://www.legapallacanestro.com/serie/4/classifica",
        "sofascore_id": 14251,   # ID Serie B Nazionale basket su Sofascore
        "girone_check": "girone b",
    },
    "A2": {
        "pb_home":      "https://www.pianetabasket.com/serie-a2/",
        "pb_section":   "/serie-a2/",
        "pb_class":     "https://www.pianetabasket.com/serie-a2/classifica-serie-a2-2025-26",
        "playbasket":   "https://www.playbasket.it/serie-a2",
        "lnp":          "https://www.legapallacanestro.com/serie/1/classifica",
        "girone_check": None,
    },
    "LBA": {
        "pb_home":      "https://www.pianetabasket.com/legabasket-serie-a/",
        "pb_section":   "/legabasket-serie-a/",
        "pb_class":     None,
        "playbasket":   "https://www.playbasket.it/serie-a",
        "lnp":          None,
        "girone_check": None,
    },
    "B Interregionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
        "pb_class":     None,
        "playbasket":   "https://www.playbasket.it/b-interregionale",
        "lnp":          None,
        "girone_check": None,
    },
}

BASE_MATCHES = [
    {"id":"v02","team":"virtus","phase":"regular","round":2, "date":"2025-09-28","time":"18:00","home":"Virtus GVM Roma","away":"Loreto Pesaro","sh":84,"sa":63},
    {"id":"v04","team":"virtus","phase":"regular","round":4, "date":"2025-10-12","time":"18:00","home":"Virtus GVM Roma","away":"Solbat Golfo Piombino","sh":91,"sa":68},
    {"id":"v06","team":"virtus","phase":"regular","round":6, "date":"2025-10-19","time":"18:00","home":"Virtus GVM Roma","away":"General Contractor Jesi","sh":88,"sa":71},
    {"id":"v08","team":"virtus","phase":"regular","round":8, "date":"2025-10-29","time":"20:30","home":"Virtus GVM Roma","away":"UP Andrea Costa Imola","sh":79,"sa":74},
    {"id":"v09","team":"virtus","phase":"regular","round":9, "date":"2025-11-02","time":"18:00","home":"Virtus GVM Roma","away":"Adamant Ferrara","sh":94,"sa":66},
    {"id":"v11","team":"virtus","phase":"regular","round":11,"date":"2025-11-12","time":"20:30","home":"Virtus GVM Roma","away":"Virtus Imola","sh":88,"sa":75},
    {"id":"v13","team":"virtus","phase":"regular","round":13,"date":"2025-11-23","time":"18:00","home":"Virtus GVM Roma","away":"Pielle Livorno","sh":70,"sa":68},
    {"id":"v15","team":"virtus","phase":"regular","round":15,"date":"2025-12-07","time":"18:00","home":"Virtus GVM Roma","away":"OraSì Ravenna","sh":87,"sa":73},
    {"id":"v16","team":"virtus","phase":"regular","round":16,"date":"2025-12-14","time":"18:00","home":"Virtus GVM Roma","away":"Paperdi Juvecaserta","sh":99,"sa":63},
    {"id":"v18","team":"virtus","phase":"regular","round":18,"date":"2025-12-21","time":"18:00","home":"Virtus GVM Roma","away":"Luiss Roma","sh":71,"sa":72},
    {"id":"v21","team":"virtus","phase":"regular","round":21,"date":"2026-01-11","time":"18:00","home":"Virtus GVM Roma","away":"PSA Basket Casoria","sh":86,"sa":60},
    {"id":"v23","team":"virtus","phase":"regular","round":23,"date":"2026-01-25","time":"18:00","home":"Virtus GVM Roma","away":"Allianz Pazienza San Severo","sh":95,"sa":61},
    {"id":"v25","team":"virtus","phase":"regular","round":25,"date":"2026-02-08","time":"18:00","home":"Virtus GVM Roma","away":"Power Basket Nocera","sh":82,"sa":70},
    {"id":"v28","team":"virtus","phase":"regular","round":28,"date":"2026-02-22","time":"18:00","home":"Virtus GVM Roma","away":"Raggisolaris Faenza","sh":88,"sa":74},
    {"id":"v32","team":"virtus","phase":"regular","round":32,"date":"2026-03-21","time":"20:00","home":"Virtus GVM Roma","away":"Ristopro Fabriano","sh":94,"sa":69},
    {"id":"v34","team":"virtus","phase":"regular","round":34,"date":"2026-04-04","time":"20:00","home":"Virtus GVM Roma","away":"Benacquista Latina","sh":None,"sa":None},
    {"id":"v35","team":"virtus","phase":"regular","round":35,"date":"2026-04-12","time":"18:00","home":"Virtus GVM Roma","away":"Consorzio Dany Quarrata","sh":None,"sa":None},
    {"id":"v38","team":"virtus","phase":"regular","round":38,"date":"2026-04-26","time":"18:00","home":"Virtus GVM Roma","away":"Umana San Giobbe Chiusi","sh":None,"sa":None},
    {"id":"l01","team":"luiss","phase":"regular","round":1, "date":"2025-09-21","time":"18:00","home":"Luiss Roma","away":"Umana San Giobbe Chiusi","sh":78,"sa":65},
    {"id":"l07","team":"luiss","phase":"regular","round":7, "date":"2025-10-26","time":"18:00","home":"Luiss Roma","away":"Power Basket Nocera","sh":82,"sa":71},
    {"id":"l09","team":"luiss","phase":"regular","round":9, "date":"2025-11-02","time":"18:00","home":"Luiss Roma","away":"OraSì Ravenna","sh":90,"sa":68},
    {"id":"l10","team":"luiss","phase":"regular","round":10,"date":"2025-11-09","time":"18:00","home":"Luiss Roma","away":"Ristopro Fabriano","sh":85,"sa":72},
    {"id":"l12","team":"luiss","phase":"regular","round":12,"date":"2025-11-16","time":"18:00","home":"Luiss Roma","away":"General Contractor Jesi","sh":78,"sa":63},
    {"id":"l17","team":"luiss","phase":"regular","round":17,"date":"2025-12-17","time":"20:00","home":"Luiss Roma","away":"Consorzio Dany Quarrata","sh":88,"sa":70},
    {"id":"l20","team":"luiss","phase":"regular","round":20,"date":"2026-01-04","time":"18:00","home":"Luiss Roma","away":"Benacquista Latina","sh":80,"sa":64},
    {"id":"l22","team":"luiss","phase":"regular","round":22,"date":"2026-01-18","time":"18:00","home":"Luiss Roma","away":"Loreto Pesaro","sh":76,"sa":69},
    {"id":"l24","team":"luiss","phase":"regular","round":24,"date":"2026-02-01","time":"18:30","home":"Luiss Roma","away":"Adamant Ferrara","sh":75,"sa":67},
    {"id":"l26","team":"luiss","phase":"regular","round":26,"date":"2026-02-14","time":"18:30","home":"Luiss Roma","away":"Virtus Imola","sh":73,"sa":77},
    {"id":"l27","team":"luiss","phase":"regular","round":27,"date":"2026-02-18","time":"20:00","home":"Luiss Roma","away":"Paperdi Juvecaserta","sh":69,"sa":80},
    {"id":"l29","team":"luiss","phase":"regular","round":29,"date":"2026-03-01","time":"18:00","home":"Luiss Roma","away":"UP Andrea Costa Imola","sh":85,"sa":72},
    {"id":"l31","team":"luiss","phase":"regular","round":31,"date":"2026-03-08","time":"17:00","home":"Luiss Roma","away":"Allianz Pazienza San Severo","sh":68,"sa":70},
    {"id":"l33","team":"luiss","phase":"regular","round":33,"date":"2026-03-28","time":"18:30","home":"Luiss Roma","away":"Virtus GVM Roma","sh":None,"sa":None},
    {"id":"l36","team":"luiss","phase":"regular","round":36,"date":"2026-04-15","time":"15:00","home":"Luiss Roma","away":"Raggisolaris Faenza","sh":None,"sa":None},
    {"id":"l37","team":"luiss","phase":"regular","round":37,"date":"2026-04-19","time":"18:00","home":"Luiss Roma","away":"Pielle Livorno","sh":None,"sa":None},
]

BASE_STANDINGS = {
    "virtus": {"pos": 2, "pts": 48, "w": 24, "l": 6},
    "luiss":  {"pos": 5, "pts": 38, "w": 19, "l": 10},
}

# ================================================================
# UTILITY
# ================================================================

def fetch(url, timeout=5):
    """Fetch con timeout aggressivo per limitare i tempi di esecuzione."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/5.0)",
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "it-IT,it;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️  {url[:60]}: {e}", file=sys.stderr)
        return ""


def normalise(s):
    s = s.lower()
    for old, new in [
        ("virtus gvm roma 1960", "virtus roma"),
        ("virtus gvm roma", "virtus roma"),
        ("luiss roma", "luiss"), ("luiss basketball", "luiss"),
        ("consorzio leonardo dany quarrata", "quarrata"),
        ("consorzio dany quarrata", "quarrata"),
        ("paperdi juvecaserta 2021", "juvecaserta"),
        ("malvin psa basket casoria", "casoria"),
        ("psa basket casoria", "casoria"),
        ("verodol cbd pielle livorno", "pielle livorno"),
        ("up andrea costa imola", "andrea costa"),
        ("benacquista assicurazioni latina", "latina"),
        ("allianz pazienza san severo", "san severo"),
        ("umana san giobbe chiusi", "chiusi"),
        ("general contractor jesi", "jesi"),
        ("solbat golfo piombino", "piombino"),
        ("orasì ravenna", "ravenna"), ("orasi ravenna", "ravenna"),
        ("power basket nocera", "nocera"),
        ("adamant ferrara basket 2018", "ferrara"),
        ("adamant ferrara", "ferrara"),
        ("virtus pallacanestro imola", "v.imola"),
        ("virtus imola", "v.imola"),
        ("ristopro janus fabriano", "fabriano"),
        ("ristopro fabriano", "fabriano"),
        ("raggisolaris faenza", "faenza"),
        ("consultinvest loreto pesaro", "loreto pesaro"),
    ]:
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()


def parse_results(html):
    """
    Estrae risultati e orari futuri da HTML pianetabasket.
    Pattern con risultato:  DD/MM/YYYY HH:MM Casa - Ospite NN-NN
    Pattern solo orario:    DD/MM/YYYY HH:MM Casa - Ospite
    """
    results = []
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    seen = set()

    # Con risultato
    pat_score = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s+"
        r"(\d{2,3})-(\d{2,3})(?:\s|$)"
    )
    for m in pat_score.finditer(plain):
        dr, t, h, a, sh, sa = m.groups()
        h = h.strip(); a = a.strip()
        if len(h) < 4 or len(a) < 4:
            continue
        try:
            dd, mm, yyyy = dr.split("/")
            key = f"{yyyy}-{mm}-{dd}|{normalise(h)}"
            results.append({
                "date": f"{yyyy}-{mm}-{dd}", "time": t,
                "home": h, "away": a, "sh": int(sh), "sa": int(sa)
            })
            seen.add(key)
        except Exception:
            continue

    # Solo orario (partite future)
    pat_time = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)"
        r"(?=\s+\d{2}/\d{2}/|\s*$)"
    )
    for m in pat_time.finditer(plain):
        dr, t, h, a = m.groups()
        h = h.strip(); a = a.strip()
        if len(h) < 4 or len(a) < 4:
            continue
        try:
            dd, mm, yyyy = dr.split("/")
            key = f"{yyyy}-{mm}-{dd}|{normalise(h)}"
            if key not in seen:
                results.append({
                    "date": f"{yyyy}-{mm}-{dd}", "time": t,
                    "home": h, "away": a, "sh": None, "sa": None
                })
                seen.add(key)
        except Exception:
            continue

    return results


def parse_standings_from_html(html, aliases_v, aliases_l):
    """Estrae la classifica Girone B più aggiornata dalla pagina."""
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    best = None
    best_total = 0

    for idx in [m.start() for m in re.finditer(r"[Cc]lassifica\s+girone\s+[Bb]", plain)]:
        block = plain[idx:idx + 2500]
        for stop in ["classifica girone a", "nota -"]:
            cut = block.lower().find(stop, 20)
            if cut != -1:
                block = block[:cut]
                break

        candidate = {}
        pos = 1
        pat = re.compile(
            r"([A-Za-zÀ-ÿ0-9 '\.\-]{4,50}?)\s+(\d{1,3})\s+(\d{1,2})-(\d{1,2})(?:\s|$)"
        )
        for m in pat.finditer(block):
            name = m.group(1).strip()
            pts, w, l = int(m.group(2)), int(m.group(3)), int(m.group(4))
            nl = name.lower()
            if any(a in nl for a in aliases_v) and "virtus" not in candidate:
                candidate["virtus"] = {"pos": pos, "pts": pts, "w": w, "l": l}
            elif any(a in nl for a in aliases_l) and "luiss" not in candidate:
                candidate["luiss"] = {"pos": pos, "pts": pts, "w": w, "l": l}
            pos += 1
            if len(candidate) == 2:
                break

        if len(candidate) == 2:
            total = candidate["virtus"]["pts"] + candidate["luiss"]["pts"]
            if total > best_total:
                best_total = total
                best = candidate

    return best


def find_match(scraped, match):
    mh = normalise(match["home"])
    for s in scraped:
        if s.get("date") and match.get("date"):
            try:
                md = datetime.strptime(match["date"], "%Y-%m-%d").date()
                sd = datetime.strptime(s["date"], "%Y-%m-%d").date()
                if abs((sd - md).days) > 4:
                    continue
            except Exception:
                pass
        sh_n = normalise(s["home"])
        if (sh_n in mh or mh in sh_n or
                ("virtus roma" in mh and "virtus" in sh_n) or
                ("luiss" in mh and "luiss" in sh_n)):
            return s
    return None


# ================================================================
# RICERCA URL — veloce e mirata
# ================================================================

def find_urls_from_homepage(serie, last_round):
    """
    Cerca sulla homepage di pianetabasket gli URL delle giornate
    successive all'ultima con risultato. Max 5 URL.
    """
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pb_home = sources["pb_home"]
    pb_section = sources["pb_section"]
    found = []

    html = fetch(pb_home)
    if not html:
        return found

    pat = re.compile(
        r'href=["\'](' + re.escape(pb_section) +
        r'[^"\']*(?:risultati|calendario)[^"\']*2025-26[^"\']*)["\']'
    )
    for m in pat.finditer(html):
        url = "https://www.pianetabasket.com" + m.group(1)
        rnd_m = re.search(r"-(\d+)-giornata-", url)
        rnd = int(rnd_m.group(1)) if rnd_m else None
        if rnd and rnd <= last_round:
            continue
        if url not in found:
            found.append(url)
        if len(found) >= 5:
            break

    print(f"  🔍 homepage: {len(found)} URL")
    return found


def find_urls_from_rss_and_homepage(serie, last_round):
    """
    Cerca URL reali delle giornate recenti su:
    1. RSS feed pianetabasket (URL reali garantiti, nessuna stima)
    2. Homepage come fallback
    """
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pb_section = sources["pb_section"]
    pb_home = sources["pb_home"]
    pb_rss = sources.get("pb_rss", "https://www.pianetabasket.com/feed/serie-b/")
    found = []

    # 1. RSS feed — URL reali pubblicati da pianetabasket
    rss_html = fetch(pb_rss)
    if rss_html:
        pat = re.compile(
            r"<link[^>]*>(https://www[.]pianetabasket[.]com"
            + re.escape(pb_section)
            + r"[^<]*(risultati|calendario)[^<]*2025-26[^<]*)</link>"
        )
        for m in pat.finditer(rss_html):
            url = m.group(1).strip()
            rnd_m = re.search(r"-([0-9]+)-giornata-", url)
            rnd = int(rnd_m.group(1)) if rnd_m else None
            if rnd and rnd <= last_round:
                continue
            if url not in found:
                found.append(url)
        print(f"  🔍 RSS: {len(found)} URL trovati")

    # 2. Homepage fallback
    if not found:
        html = fetch(pb_home)
        if html:
            pat2 = re.compile(
                r'href=["\']('  + re.escape(pb_section)
                + r'[^"\']*(risultati|calendario)[^"\']*2025-26-[0-9]+)["\']'
            )
            for m in pat2.finditer(html):
                url = "https://www.pianetabasket.com" + m.group(1)
                rnd_m = re.search(r"-([0-9]+)-giornata-", url)
                rnd = int(rnd_m.group(1)) if rnd_m else None
                if rnd and rnd <= last_round:
                    continue
                if url not in found:
                    found.append(url)
                if len(found) >= 5:
                    break
            print(f"  🔍 homepage fallback: {len(found)} URL")

    return found



def find_url_via_search(rnd, season="2025-26"):
    """
    Cerca l'URL reale della giornata su Google e DuckDuckGo.
    Questo è il metodo più affidabile — non dipende da stime di ID.
    Google indicizza pianetabasket entro pochi minuti dalla pubblicazione.
    """
    queries = [
        f"https://html.duckduckgo.com/html/?q=site%3Apianetabasket.com+%22{rnd}-giornata%22+%22{season}%22",
        f"https://html.duckduckgo.com/html/?q=pianetabasket+serie+b+nazionale+{rnd}+giornata+{season}+risultati+classifiche",
    ]
    pat = re.compile(
        r"href=[\x22\x27]?(https://www[.]pianetabasket[.]com/serie-b/[^\x22\x27<>\s]*"
        + str(rnd) + r"-giornata-2025-26-[0-9]+)[\x22\x27]?"
    )
    for query_url in queries:
        html = fetch(query_url, timeout=8)
        if not html:
            continue
        for m in pat.finditer(html):
            url = m.group(1)
            # Verifica che l'URL contenga risultati
            if any(s in url for s in ["risultati", "calendario", "classifiche"]):
                print(f"  🔍 search G{rnd}: trovato {url[-40:]}")
                return url
    return None


def get_urls_for_round_fast(rnd):
    """
    Trova l'URL reale della giornata con questa priorità:
    1. URL noto verificato (istantaneo)
    2. Ricerca Google/DuckDuckGo (trova URL reale senza stime)
    3. Stima ID come fallback finale
    """
    urls = []

    # 1. URL noto verificato
    if rnd in KNOWN_URLS:
        urls.append(KNOWN_URLS[rnd])
        return urls  # Se lo conosciamo già, usalo direttamente

    # 2. Ricerca su DuckDuckGo — trova l'URL reale senza stimare
    found_url = find_url_via_search(rnd)
    if found_url:
        urls.append(found_url)
        return urls

    # 3. Fallback: stima ID (usato solo se la ricerca fallisce)
    base_id = ROUND_BASE_IDS.get(rnd, 357782 + (rnd - 33) * 642)
    for suf, delta in [
        ("classifiche", 0),
        ("sabato-classifiche", 0),
        ("domenica-classifiche", 0),
        ("classifiche", -300),
        ("classifiche", +300),
    ]:
        url = (
            f"https://www.pianetabasket.com/serie-b/"
            f"serie-b-nazionale-calendario-risultati-{suf}-"
            f"{rnd}-giornata-2025-26-{base_id + delta}"
        )
        if url not in urls:
            urls.append(url)
        if len(urls) >= 5:
            break

    return urls


def fetch_schedule_sofascore():
    """
    Recupera calendario e risultati di Virtus e LUISS da Sofascore
    usando gli ID squadra diretti — molto più affidabile dell'ID torneo.
    Sofascore aggiorna date/orari in tempo reale non appena LNP li comunica.

    ID squadre verificati:
    - Virtus GVM Roma 1960: 801048
    - Luiss Roma: 285133
    """
    schedules = []
    teams = [
        ("virtus", 801048),
        ("luiss",  285133),
    ]

    for team_key, team_id in teams:
        # Partite future
        url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/next/0"
        html = fetch(url, timeout=6)
        if html:
            try:
                data = json.loads(html)
                for ev in data.get("events", []):
                    ts = ev.get("startTimestamp", 0)
                    if not ts:
                        continue
                    ht = ev.get("homeTeam", {}).get("name", "").lower()
                    at = ev.get("awayTeam", {}).get("name", "").lower()
                    # Solo partite in casa
                    if "virtus" not in ht and "luiss" not in ht:
                        continue
                    is_home = (team_key == "virtus" and "virtus" in ht) or                               (team_key == "luiss" and "luiss" in ht)
                    if not is_home:
                        continue
                    dt = datetime.fromtimestamp(ts)
                    schedules.append({
                        "team": team_key,
                        "date": dt.strftime("%Y-%m-%d"),
                        "time": dt.strftime("%H:%M"),
                        "home": ev["homeTeam"]["name"],
                        "away": ev["awayTeam"]["name"],
                        "source": "sofascore"
                    })
            except Exception as e:
                print(f"  ⚠️ Sofascore future [{team_key}]: {e}", file=sys.stderr)

        # Partite passate recenti (risultati)
        url2 = f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/0"
        html2 = fetch(url2, timeout=6)
        if html2:
            try:
                data2 = json.loads(html2)
                for ev in data2.get("events", []):
                    ts = ev.get("startTimestamp", 0)
                    ht = ev.get("homeTeam", {}).get("name", "").lower()
                    is_home = (team_key == "virtus" and "virtus" in ht) or                               (team_key == "luiss" and "luiss" in ht)
                    if not is_home:
                        continue
                    sh = ev.get("homeScore", {}).get("current")
                    sa = ev.get("awayScore", {}).get("current")
                    if sh is None or sa is None:
                        continue
                    dt = datetime.fromtimestamp(ts)
                    schedules.append({
                        "team": team_key,
                        "date": dt.strftime("%Y-%m-%d"),
                        "time": dt.strftime("%H:%M"),
                        "home": ev["homeTeam"]["name"],
                        "away": ev["awayTeam"]["name"],
                        "sh": int(sh),
                        "sa": int(sa),
                        "source": "sofascore"
                    })
            except Exception as e:
                print(f"  ⚠️ Sofascore last [{team_key}]: {e}", file=sys.stderr)

    if schedules:
        future = [s for s in schedules if not s.get("sh")]
        past   = [s for s in schedules if s.get("sh")]
        print(f"  ✅ Sofascore: {len(future)} future, {len(past)} risultati")
    else:
        print("  ⚠️ Sofascore: nessun dato (API bloccata?)")

    return schedules


def fetch_schedule_team_sites():
    """
    Cerca orari prossima casa sui siti ufficiali delle squadre.
    Estrae pattern tipo 'sabato 4 aprile ore 20:00'.
    """
    schedules = []
    months_it = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
    }
    team_urls = [
        ("virtus", "https://www.virtusroma1960.it/news/"),
        ("luiss",  "https://www.luissbasket.it/news/"),
        ("luiss",  "https://www.luissbasketball.it/news/"),
    ]
    pat = re.compile(
        r"(lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)"
        r"\s+(\d{1,2})\s+(\w+)"
        r"(?:\s+\d{4})?\s+(?:alle\s+)?ore\s+(\d{1,2}(?::\d{2})?)",
        re.IGNORECASE
    )
    for team, url in team_urls:
        html = fetch(url, timeout=5)
        if not html:
            continue
        plain = re.sub(r"<[^>]+>", " ", html)
        plain = re.sub(r"\s+", " ", plain)
        for m in pat.finditer(plain):
            _, day, month_str, time_str = m.groups()
            month = months_it.get(month_str.lower())
            if not month:
                continue
            if ":" not in time_str:
                time_str += ":00"
            try:
                dt = datetime(2026, month, int(day))
                schedules.append({
                    "team": team,
                    "date": dt.strftime("%Y-%m-%d"),
                    "time": time_str,
                    "source": url.split("/")[2]
                })
            except Exception:
                continue

    if schedules:
        print(f"  🔍 team sites: {len(schedules)} orari trovati")
    return schedules


# ================================================================
# AGGIORNAMENTO CLASSIFICA
# ================================================================

def fetch_calendar_changes(config):
    """
    Cerca variazioni di calendario negli articoli di pianetabasket.
    Pianetabasket pubblica sempre un articolo quando una partita viene spostata.
    """
    changes = []
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    months_it = {
        "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,
        "maggio":5,"giugno":6,"luglio":7,"agosto":8,
        "settembre":9,"ottobre":10,"novembre":11,"dicembre":12
    }
    keywords = ["modif", "anticip", "posticip", "spostata", "rinviata", "recupero"]
    candidate_urls = []

    # 1. RSS feed
    rss_html = fetch("https://www.pianetabasket.com/feed/serie-b/")
    if rss_html:
        for m in re.finditer(
            r"<link[^>]*>(https://www[.]pianetabasket[.]com/serie-b/[^<]+)</link>",
            rss_html
        ):
            url = m.group(1).strip()
            if any(k in url.lower() for k in keywords):
                candidate_urls.append(url)

    # 2. Homepage
    home_html = fetch("https://www.pianetabasket.com/serie-b/")
    if home_html:
        for m in re.finditer(r"(/serie-b/[^<>]{5,80})", home_html):
            path = m.group(1)
            if any(k in path.lower() for k in keywords):
                url = "https://www.pianetabasket.com" + path
                if url not in candidate_urls:
                    candidate_urls.append(url)

    print(f"  \U0001f50d Articoli modifica calendario: {len(candidate_urls)}")

    for url in candidate_urls[:5]:
        art = fetch(url)
        if not art:
            continue
        plain = re.sub(r"<[^>]+>", " ", art)
        plain = re.sub(r"\s+", " ", plain)
        pl = plain.lower()

        is_virtus = any(a in pl for a in aliases_v)
        is_luiss  = any(a in pl for a in aliases_l)
        if not is_virtus and not is_luiss:
            continue
        team = "virtus" if is_virtus else "luiss"

        # Cerca DD/MM/YYYY HH:MM
        m1 = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", plain)
        if m1:
            dd, mm, yyyy, t = m1.groups()
            changes.append({"team": team, "date": f"{yyyy}-{mm}-{dd}", "time": t, "source": url})
            print(f"  \U0001f4c5 [{team}] {yyyy}-{mm}-{dd} ore {t}")
            continue

        # Cerca "11 aprile ore 20"
        m2 = re.search(
            r"(\d{1,2})\s+(\w+)(?:\s+2026)?\s+(?:ore|alle)\s+(\d{1,2}(?::\d{2})?)",
            plain, re.IGNORECASE
        )
        if m2:
            day, mon_str, t = m2.groups()
            mon = months_it.get(mon_str.lower())
            if mon:
                if ":" not in t:
                    t += ":00"
                changes.append({
                    "team": team,
                    "date": f"2026-{mon:02d}-{int(day):02d}",
                    "time": t, "source": url
                })
                print(f"  \U0001f4c5 [{team}] 2026-{mon:02d}-{int(day):02d} ore {t}")

    return changes


def update_standings_multi(standings, config, scraped_htmls):
    """Aggiorna classifica da più fonti, prende quella con punteggio più alto."""
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    candidates = []

    # Da pagine già scaricate
    for label, html in scraped_htmls:
        if not html:
            continue
        st = parse_standings_from_html(html, aliases_v, aliases_l)
        if st:
            candidates.append((label, st))

    # Pagina classifica pianetabasket
    pb_class = sources.get("pb_class")
    if pb_class:
        html = fetch(pb_class)
        if html:
            st = parse_standings_from_html(html, aliases_v, aliases_l)
            if st:
                candidates.append(("pb-class", st))

    # LNP ufficiale
    lnp_url = sources.get("lnp")
    if lnp_url:
        html = fetch(lnp_url)
        if html:
            st = parse_standings_from_html(html, aliases_v, aliases_l)
            if st:
                candidates.append(("lnp", st))

    if not candidates:
        print("  ⚠️  Nessuna classifica trovata")
        return standings

    best_label, best = max(
        candidates,
        key=lambda x: x[1]["virtus"]["pts"] + x[1]["luiss"]["pts"]
    )
    current_total = (
        standings.get("virtus", {}).get("pts", 0) +
        standings.get("luiss", {}).get("pts", 0)
    )
    new_total = best["virtus"]["pts"] + best["luiss"]["pts"]

    if new_total >= current_total:
        print(
            f"  ✅ Classifica [{best_label}]: "
            f"Virtus {best['virtus']['pos']}° {best['virtus']['pts']}pt "
            f"({best['virtus']['w']}V-{best['virtus']['l']}P) | "
            f"LUISS {best['luiss']['pos']}° {best['luiss']['pts']}pt "
            f"({best['luiss']['w']}V-{best['luiss']['l']}P)"
        )
        return best

    print("  ℹ️  Classifica già aggiornata")
    return standings


# ================================================================
# AGGIORNAMENTO IN STAGIONE
# ================================================================

def update_in_season(matches, config, standings):
    today = date.today()
    rounds_done = [
        m["round"] for m in matches
        if m.get("sh") is not None and m.get("phase") == "regular"
    ]
    last_round = max(rounds_done) if rounds_done else 0
    print(f"  Ultima giornata con risultati: {last_round}")

    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    girone_check = sources.get("girone_check")

    all_scraped = []
    scraped_htmls = []

    # STEP 1: URL dalla homepage (veloci, trovano le giornate recenti)
    home_urls = find_urls_from_rss_and_homepage(serie, last_round)
    for url in home_urls:
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        if girone_check and girone_check not in html.lower():
            continue
        scraped = parse_results(html)
        if scraped:
            rnd_m = re.search(r"-(\d+)-giornata-", url)
            rnd = rnd_m.group(1) if rnd_m else "?"
            print(f"  ✅ homepage G{rnd}: {len(scraped)} risultati")
            all_scraped.extend(scraped)
            scraped_htmls.append((f"G{rnd}", html))

    # STEP 2: URL mirati per le giornate senza risultato (max 3 URL per giornata)
    found_rounds = set()
    for _, html in scraped_htmls:
        rnd_m = re.search(r"giornata\s+(\d+)", html.lower())
        if rnd_m:
            found_rounds.add(int(rnd_m.group(1)))

    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        rnd = m.get("round")
        if not rnd or m.get("sh") is not None:
            continue
        if md > today + timedelta(days=60):
            continue  # non cercare partite troppo lontane
        if rnd in found_rounds:
            continue

        urls = get_urls_for_round_fast(rnd)
        for url in urls:
            html = fetch(url)
            if not html or len(html) < 1000:
                continue
            if girone_check and girone_check not in html.lower():
                continue
            scraped = parse_results(html)
            if scraped:
                print(f"  ✅ fallback G{rnd}: {len(scraped)} risultati")
                all_scraped.extend(scraped)
                scraped_htmls.append((f"G{rnd}", html))
                found_rounds.add(rnd)
                break

    # STEP 3: Variazioni di calendario da articoli pianetabasket
    print("\n  📅 Ricerca variazioni calendario...")
    calendar_changes = fetch_calendar_changes(config)

    # Applica variazioni calendario alle partite future
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if md < today or m.get("sh") is not None:
            continue
        for chg in calendar_changes:
            if chg.get("team") != m["team"]:
                continue
            try:
                chg_d = datetime.strptime(chg["date"], "%Y-%m-%d").date()
                if abs((chg_d - md).days) <= 7 and (
                    chg["date"] != m["date"] or chg["time"] != m.get("time")
                ):
                    print(f"  📅 {m['home']} vs {m['away']}: {m['date']} {m.get('time','')} → {chg['date']} {chg['time']}")
                    m["date"] = chg["date"]
                    m["time"] = chg["time"]
                    break
            except Exception:
                continue

    # STEP 4: Orari futuri da Sofascore e siti squadre
    print("\n  📅 Ricerca orari futuri...")
    extra = fetch_schedule_sofascore() + fetch_schedule_team_sites()

    # Applica risultati e orari
    updated = 0
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()

        # Risultato partita passata
        if md < today and m.get("sh") is None:
            found = find_match(all_scraped, m)
            if found:
                m["sh"] = found["sh"]
                m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  ✅ {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1

        # Orario/data partita futura — da pianetabasket
        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print("  orario aggiornato (pianetabasket): " + str(m.get("home")) + " vs " + str(m.get("away")))
                m["time"] = found["time"]
                updated += 1

        # Orario/data partita futura — da Sofascore e siti squadre
        # Sofascore aggiorna variazioni calendario in tempo reale
        if md >= today:
            for sched in extra:
                try:
                    if sched.get("team") != m["team"]:
                        continue
                    if sched.get("sh") is not None:
                        continue
                    smd = datetime.strptime(sched["date"], "%Y-%m-%d").date()
                    away_n = normalise(sched.get("away", ""))
                    m_away_n = normalise(m.get("away", ""))
                    same_away = away_n in m_away_n or m_away_n in away_n
                    if not same_away or abs((smd - md).days) > 7:
                        continue
                    changed = False
                    if sched["date"] != m["date"]:
                        print("  data aggiornata: " + str(m.get("home")) + " vs " + str(m.get("away")))
                        m["date"] = sched["date"]
                        changed = True
                    if sched.get("time") and sched["time"] != m.get("time"):
                        print("  orario aggiornato: " + str(m.get("home")) + " vs " + str(m.get("away")))
                        m["time"] = sched["time"]
                        changed = True
                    if changed:
                        updated += 1
                    break
                except Exception:
                    continue

        # Risultato da Sofascore per partite passate non ancora trovate
        if md < today and m.get("sh") is None:
            for sched in extra:
                try:
                    if sched.get("team") != m["team"] or sched.get("sh") is None:
                        continue
                    smd = datetime.strptime(sched["date"], "%Y-%m-%d").date()
                    away_n = normalise(sched.get("away", ""))
                    m_away_n = normalise(m.get("away", ""))
                    same_away = away_n in m_away_n or m_away_n in away_n
                    if same_away and abs((smd - md).days) <= 2:
                        m["sh"] = sched["sh"]
                        m["sa"] = sched["sa"]
                        if sched.get("time"):
                            m["time"] = sched["time"]
                        print("  risultato sofascore: " + str(m.get("home")) + " vs " + str(m.get("away")))
                        updated += 1
                        break
                except Exception:
                    continue
    # STEP 4: Classifica
    print("\n  🏆 Aggiornamento classifica...")
    standings = update_standings_multi(standings, config, scraped_htmls)

    return updated, standings


# ================================================================
# FUORI STAGIONE
# ================================================================

def search_new_calendar(next_season, config):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    pdf_urls = [
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{next_season}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._a_{next_season}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{next_season}.pdf",
    ]
    serie_map = ["B Nazionale", "B Nazionale", "A2"]

    for pdf_url, serie in zip(pdf_urls, serie_map):
        html = fetch(pdf_url, timeout=8)
        if not html or len(html) < 500:
            continue
        for team_key, team_cfg in config["teams"].items():
            for alias in team_cfg.get("name_aliases", []):
                if alias in html.lower():
                    new_matches = parse_pdf(html)
                    if new_matches:
                        config["teams"][team_key]["serie"] = serie
                        print(f"  📄 {team_cfg['name']} trovato in {serie}")
                        return new_matches, next_season

    for url in [
        "https://www.legapallacanestro.com/serie/4/calendario",
        "https://www.pianetabasket.com/serie-b/",
    ]:
        html = fetch(url)
        if html and next_season in html:
            for team_cfg in config["teams"].values():
                for alias in team_cfg.get("name_aliases", []):
                    if alias in html.lower():
                        print(f"  🌐 Nuova stagione {next_season} rilevata")
                        return None, next_season

    print(f"  ℹ️  Calendario {next_season} non ancora disponibile")
    return None, None


def parse_pdf(text):
    new_matches = []
    for line in text.split("\n"):
        line = line.strip()
        m = re.match(r"(\d{1,2})\s+(\d{2}/\d{2}/\d{4})\s+(.*)", line)
        if not m:
            continue
        rnd, date_raw, rest = int(m.group(1)), m.group(2), m.group(3)
        parts = re.split(r"\s{2,}", rest.strip())
        if len(parts) < 2:
            continue
        home, away = parts[0].strip(), parts[1].strip()
        hn = normalise(home)
        team = None
        if "virtus roma" in hn or "virtus gvm" in hn:
            team = "virtus"
        elif "luiss" in hn:
            team = "luiss"
        if not team:
            continue
        dd, mm, yyyy = date_raw.split("/")
        new_matches.append({
            "id": f"{team[0]}{rnd:02d}", "team": team,
            "phase": "regular", "round": rnd,
            "date": f"{yyyy}-{mm}-{dd}", "time": "",
            "home": home, "away": away, "sh": None, "sa": None,
        })
    return new_matches


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v5 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches   = current.get("matches", [dict(m) for m in BASE_MATCHES])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config    = current.get("config", CONFIG)
        # Retrocompatibilità
        for team_key, team_default in CONFIG["teams"].items():
            if team_key not in config.get("teams", {}):
                config.setdefault("teams", {})[team_key] = team_default
            else:
                for field, val in team_default.items():
                    config["teams"][team_key].setdefault(field, val)
        config.setdefault("next_season", CONFIG["next_season"])
        print(f"📂 Caricato — {len(matches)} partite, stagione {config.get('season','?')}")
    else:
        matches   = [dict(m) for m in BASE_MATCHES]
        standings = dict(BASE_STANDINGS)
        config    = CONFIG
        print("📂 Primo avvio — dati base")

    today       = date.today()
    next_season = config.get("next_season", "2026-27")
    all_dates   = [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in matches]
    season_end  = max(all_dates) if all_dates else date(2026, 6, 30)
    in_season   = today <= season_end + timedelta(days=30)

    total_updated = 0

    if in_season:
        serie_v = config["teams"]["virtus"].get("serie", "?")
        serie_l = config["teams"]["luiss"].get("serie", "?")
        print(f"\n📅 IN STAGIONE — Virtus: {serie_v} | LUISS: {serie_l}")
        total_updated, standings = update_in_season(matches, config, standings)
        print(f"\n📝 Aggiornamenti: {total_updated}")
    else:
        print(f"\n💤 FUORI STAGIONE — cerco {next_season}")
        new_matches, found = search_new_calendar(next_season, config)
        if new_matches and found:
            matches = new_matches
            standings = {
                "virtus": {"pos": 0, "pts": 0, "w": 0, "l": 0},
                "luiss":  {"pos": 0, "pts": 0, "w": 0, "l": 0},
            }
            yr = int(found[:4])
            config["season"] = found
            config["next_season"] = f"{yr+1}-{str(yr+2)[2:]}"
            total_updated = len(new_matches)
        elif found:
            print(f"ℹ️  Stagione {found} rilevata, calendario non disponibile")
        else:
            print("ℹ️  Nessuna novità")

    output = {
        "last_updated": datetime.now().isoformat(),
        "season": config.get("season", "2025-26"),
        "config": config,
        "matches": matches,
        "standings": standings,
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Salvato — {len(matches)} partite")
    print("✅ Completato!\n")
    return total_updated


if __name__ == "__main__":
    main()
