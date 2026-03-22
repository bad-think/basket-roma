#!/usr/bin/env python3
"""
update_data.py — Aggiornamento automatico Roma Basket Casa
Gira ogni notte via GitHub Actions.

Fonti risultati (nazionali):
  1. pianetabasket.com  — principale, copre tutte le serie
  2. playbasket.it      — backup nazionale, copre B, B Interregionale, A2
  3. legapallacanestro.com — ufficiale LNP, classifica e calendario

Campionati supportati (auto-rilevamento):
  - Serie B Nazionale
  - Serie A2
  - LBA Serie A
  - Serie B Interregionale
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE — aggiorna qui a inizio stagione
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
# CAMPIONATI SUPPORTATI
# Ogni entry ha le URL delle fonti per quella serie
# ================================================================
LEAGUE_SOURCES = {
    "B Nazionale": {
        "pianetabasket": "https://www.pianetabasket.com/serie-b/",
        "playbasket":    "https://www.playbasket.it/serie-b",
        "lnp":           "https://www.legapallacanestro.com/serie/4/classifica",
        "girone_check":  "girone b",
        "pb_section":    "/serie-b/",
    },
    "A2": {
        "pianetabasket": "https://www.pianetabasket.com/serie-a2/",
        "playbasket":    "https://www.playbasket.it/serie-a2",
        "lnp":           "https://www.legapallacanestro.com/serie/1/classifica",
        "girone_check":  None,
        "pb_section":    "/serie-a2/",
    },
    "LBA": {
        "pianetabasket": "https://www.pianetabasket.com/legabasket-serie-a/",
        "playbasket":    "https://www.playbasket.it/serie-a",
        "lnp":           None,
        "girone_check":  None,
        "pb_section":    "/legabasket-serie-a/",
    },
    "B Interregionale": {
        "pianetabasket": "https://www.pianetabasket.com/serie-b/",
        "playbasket":    "https://www.playbasket.it/b-interregionale",
        "lnp":           None,
        "girone_check":  None,
        "pb_section":    "/serie-b/",
    },
}

# ================================================================
# CALENDARIO BASE
# ================================================================
BASE_MATCHES = [
    {"id":"v02","team":"virtus","phase":"regular","round":2, "date":"2025-09-28","time":"18:00","home":"Virtus GVM Roma","away":"Loreto Pesaro","sh":84,"sa":63},
    {"id":"v04","team":"virtus","phase":"regular","round":4, "date":"2025-10-12","time":"18:00","home":"Virtus GVM Roma","away":"Solbat Golfo Piombino","sh":91,"sa":68},
    {"id":"v06","team":"virtus","phase":"regular","round":6, "date":"2025-10-19","time":"18:00","home":"Virtus GVM Roma","away":"General Contractor Jesi","sh":88,"sa":71},
    {"id":"v08","team":"virtus","phase":"regular","round":8, "date":"2025-10-29","time":"20:30","home":"Virtus GVM Roma","away":"UP Andrea Costa Imola","sh":79,"sa":74},
    {"id":"v09","team":"virtus","phase":"regular","round":9, "date":"2025-11-02","time":"18:00","home":"Virtus GVM Roma","away":"Adamant Ferrara","sh":94,"sa":66},
    {"id":"v11","team":"virtus","phase":"regular","round":11,"date":"2025-11-12","time":"20:30","home":"Virtus GVM Roma","away":"Virtus Imola","sh":88,"sa":75},
    {"id":"v13","team":"virtus","phase":"regular","round":13,"date":"2025-11-23","time":"18:00","home":"Virtus GVM Roma","away":"Pielle Livorno","sh":None,"sa":None},
    {"id":"v15","team":"virtus","phase":"regular","round":15,"date":"2025-12-07","time":"18:00","home":"Virtus GVM Roma","away":"OraSì Ravenna","sh":87,"sa":73},
    {"id":"v16","team":"virtus","phase":"regular","round":16,"date":"2025-12-14","time":"18:00","home":"Virtus GVM Roma","away":"Paperdi Juvecaserta","sh":99,"sa":63},
    {"id":"v18","team":"virtus","phase":"regular","round":18,"date":"2025-12-21","time":"18:00","home":"Virtus GVM Roma","away":"Luiss Roma","sh":None,"sa":None},
    {"id":"v21","team":"virtus","phase":"regular","round":21,"date":"2026-01-11","time":"18:00","home":"Virtus GVM Roma","away":"PSA Basket Casoria","sh":86,"sa":60},
    {"id":"v23","team":"virtus","phase":"regular","round":23,"date":"2026-01-25","time":"18:00","home":"Virtus GVM Roma","away":"Allianz Pazienza San Severo","sh":95,"sa":61},
    {"id":"v25","team":"virtus","phase":"regular","round":25,"date":"2026-02-08","time":"18:00","home":"Virtus GVM Roma","away":"Power Basket Nocera","sh":82,"sa":70},
    {"id":"v28","team":"virtus","phase":"regular","round":28,"date":"2026-02-22","time":"18:00","home":"Virtus GVM Roma","away":"Raggisolaris Faenza","sh":88,"sa":74},
    {"id":"v32","team":"virtus","phase":"regular","round":32,"date":"2026-03-21","time":"20:00","home":"Virtus GVM Roma","away":"Ristopro Fabriano","sh":94,"sa":69},
    {"id":"v34","team":"virtus","phase":"regular","round":34,"date":"2026-04-05","time":"18:00","home":"Virtus GVM Roma","away":"Benacquista Latina","sh":None,"sa":None},
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
    {"id":"l33","team":"luiss","phase":"regular","round":33,"date":"2026-03-29","time":"18:00","home":"Luiss Roma","away":"Virtus GVM Roma","sh":None,"sa":None},
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

def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/3.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "it-IT,it;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️  {url[:65]}: {e}", file=sys.stderr)
        return ""


def normalise(s):
    s = s.lower()
    subs = [
        ("virtus gvm roma 1960", "virtus roma"),
        ("virtus gvm roma", "virtus roma"),
        ("luiss roma", "luiss"),
        ("luiss basketball", "luiss"),
        ("consorzio leonardo dany quarrata", "quarrata"),
        ("consorzio dany quarrata", "quarrata"),
        ("paperdi juvecaserta 2021", "juvecaserta"),
        ("paperdi juve caserta", "juvecaserta"),
        ("malvin psa basket casoria", "casoria"),
        ("psa basket casoria", "casoria"),
        ("verodol cbd pielle livorno", "pielle livorno"),
        ("up andrea costa imola", "andrea costa"),
        ("benacquista assicurazioni latina", "latina"),
        ("allianz pazienza san severo", "san severo"),
        ("umana san giobbe chiusi", "chiusi"),
        ("general contractor jesi", "jesi"),
        ("solbat golfo piombino", "piombino"),
        ("solbat basket golfo piombino", "piombino"),
        ("orasì ravenna", "ravenna"),
        ("orasi ravenna", "ravenna"),
        ("power basket nocera", "nocera"),
        ("adamant ferrara basket 2018", "ferrara"),
        ("adamant ferrara", "ferrara"),
        ("virtus pallacanestro imola", "v.imola"),
        ("virtus imola", "v.imola"),
        ("ristopro janus fabriano", "fabriano"),
        ("ristopro fabriano", "fabriano"),
        ("raggisolaris faenza", "faenza"),
        ("tema sinergie faenza", "faenza"),
        ("consultinvest loreto pesaro", "loreto pesaro"),
        ("loreto basket pesaro", "loreto pesaro"),
        ("ea7 emporio armani milano", "olimpia milano"),
        ("reyer venezia", "venezia"),
    ]
    for old, new in subs:
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()


def parse_results(html):
    """Parser universale per pianetabasket e siti simili."""
    results = []
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"  +", " ", plain)

    # Pattern con data: DD/MM/YYYY HH:MM Casa-Ospite NN-NN
    pat = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s+"
        r"(\d{2,3})-(\d{2,3})(?:\s|$)"
    )
    for m in pat.finditer(plain):
        dr, t, h, a, sh, sa = m.groups()
        h = h.strip(); a = a.strip()
        if len(h) < 4 or len(a) < 4:
            continue
        try:
            dd, mm, yyyy = dr.split("/")
            results.append({
                "date": f"{yyyy}-{mm}-{dd}",
                "time": t,
                "home": h,
                "away": a,
                "sh": int(sh),
                "sa": int(sa)
            })
        except Exception:
            continue

    return results


def parse_standings(html, team_aliases_v, team_aliases_l):
    """Estrae classifica Girone B da pianetabasket — posizione, punti, V, P."""
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    # Cerca il blocco "Classifica girone B"
    idx = plain.lower().find("classifica girone b")
    if idx == -1:
        return None

    block = plain[idx:idx + 2500]

    # Taglia prima della classifica Girone A o NOTA
    for stop in ["classifica girone a", "classifica girone a", "nota -", "nota-"]:
        cut = block.lower().find(stop, 20)
        if cut != -1:
            block = block[:cut]
            break

    standings = {}
    pos = 1
    # Cerca righe tipo "Virtus GVM Roma 1960 48 24-6"
    pat = re.compile(r"([A-Za-zÀ-ÿ0-9 '\.\-]{4,50}?)\s+(\d{1,3})\s+(\d{1,2})-(\d{1,2})(?:\s|$)")
    for m in pat.finditer(block):
        name = m.group(1).strip()
        pts  = int(m.group(2))
        w    = int(m.group(3))
        l    = int(m.group(4))
        nl   = name.lower()

        is_virtus = any(a in nl for a in team_aliases_v)
        is_luiss  = any(a in nl for a in team_aliases_l)

        if is_virtus and "virtus" not in standings:
            standings["virtus"] = {"pos": pos, "pts": pts, "w": w, "l": l}
        elif is_luiss and "luiss" not in standings:
            standings["luiss"]  = {"pos": pos, "pts": pts, "w": w, "l": l}

        pos += 1
        if len(standings) == 2:
            break

    return standings if len(standings) == 2 else None

def parse_standings_playbasket(html, team_aliases_v, team_aliases_l):
    """Estrae classifica da playbasket.it"""
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    # playbasket usa pattern simile: cerca "classifica" o "standings"
    for keyword in ["classifica", "standings", "girone b"]:
        idx = plain.lower().find(keyword)
        if idx != -1:
            break
    else:
        return None

    block = plain[idx:idx + 2500]
    standings = {}
    pos = 1
    pat = re.compile(r"([A-Za-zÀ-ÿ0-9 '\.\-]{4,50}?)\s+(\d{1,3})\s+(\d{1,2})-(\d{1,2})(?:\s|$)")
    for m in pat.finditer(block):
        name = m.group(1).strip()
        pts  = int(m.group(2))
        w    = int(m.group(3))
        l    = int(m.group(4))
        nl   = name.lower()
        if any(a in nl for a in team_aliases_v) and "virtus" not in standings:
            standings["virtus"] = {"pos": pos, "pts": pts, "w": w, "l": l}
        elif any(a in nl for a in team_aliases_l) and "luiss" not in standings:
            standings["luiss"]  = {"pos": pos, "pts": pts, "w": w, "l": l}
        pos += 1
        if len(standings) == 2:
            break
    return standings if len(standings) == 2 else None


def parse_standings_lnp(html, team_aliases_v, team_aliases_l):
    """
    Estrae classifica da legapallacanestro.com
    La pagina /serie/4/classifica ha dati parziali in HTML
    prima del caricamento JS — cerca pattern tabella.
    """
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    standings = {}
    pos = 1
    # LNP usa formato: "N. NomeSquadra G V P PF PS +/- Pt"
    pat = re.compile(
        r"(\d{1,2})\s+([A-Za-zÀ-ÿ0-9 '\.\-]{4,50}?)\s+\d+\s+(\d{1,2})\s+(\d{1,2})\s+\d+\s+\d+\s+[+-]?\d+\s+(\d{1,3})"
    )
    for m in pat.finditer(plain):
        rank = int(m.group(1))
        name = m.group(2).strip()
        w    = int(m.group(3))
        l    = int(m.group(4))
        pts  = int(m.group(5))
        nl   = name.lower()
        if any(a in nl for a in team_aliases_v) and "virtus" not in standings:
            standings["virtus"] = {"pos": rank, "pts": pts, "w": w, "l": l}
        elif any(a in nl for a in team_aliases_l) and "luiss" not in standings:
            standings["luiss"]  = {"pos": rank, "pts": pts, "w": w, "l": l}
        if len(standings) == 2:
            break
    return standings if len(standings) == 2 else None


def fetch_all_standings(config, standings):
    """
    Recupera la classifica da più fonti nazionali e restituisce
    quella più aggiornata (punteggio più alto = dati più recenti).
    """
    aliases_v = config["teams"]["virtus"]["name_aliases"]
    aliases_l = config["teams"]["luiss"]["name_aliases"]
    serie     = config["teams"]["virtus"]["serie"]
    sources   = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])

    candidates = []

    # 1. pianetabasket — pagina classifica dedicata
    pb_url = sources.get("pianetabasket", "").rstrip("/") + "/classifica-serie-b-nazionale-girone-b-2025-26"
    html = fetch(pb_url)
    if html:
        st = parse_standings(html, aliases_v, aliases_l)
        if st:
            candidates.append(("pianetabasket-classifica", st))
            print(f"  📊 pianetabasket classifica: Virtus {st['virtus']['pts']}pt | LUISS {st['luiss']['pts']}pt")

    # 2. legapallacanestro.com — pagina classifica ufficiale
    lnp_url = sources.get("lnp")
    if lnp_url:
        html = fetch(lnp_url)
        if html:
            st = parse_standings_lnp(html, aliases_v, aliases_l)
            if st:
                candidates.append(("lnp", st))
                print(f"  📊 lnp classifica: Virtus {st['virtus']['pts']}pt | LUISS {st['luiss']['pts']}pt")

    # 3. playbasket.it — sezione classifica
    pp_url = sources.get("playbasket", "")
    if pp_url:
        for suffix in ["/classifica", ""]:
            html = fetch(pp_url + suffix)
            if html:
                st = parse_standings_playbasket(html, aliases_v, aliases_l)
                if st:
                    candidates.append(("playbasket", st))
                    print(f"  📊 playbasket classifica: Virtus {st['virtus']['pts']}pt | LUISS {st['luiss']['pts']}pt")
                    break

    if not candidates:
        print("  ⚠️  Nessuna classifica trovata dai siti")
        return standings

    # Prendi il candidato con il punteggio più alto (= dati più recenti)
    best = max(candidates, key=lambda x: x[1]["virtus"]["pts"] + x[1]["luiss"]["pts"])
    best_name, best_st = best

    current_total = standings.get("virtus", {}).get("pts", 0) + standings.get("luiss", {}).get("pts", 0)
    new_total     = best_st["virtus"]["pts"] + best_st["luiss"]["pts"]

    if new_total >= current_total:
        print(f"  ✅ Classifica aggiornata da {best_name}: Virtus {best_st['virtus']['pos']}° {best_st['virtus']['pts']}pt ({best_st['virtus']['w']}V-{best_st['virtus']['l']}P) | LUISS {best_st['luiss']['pos']}° {best_st['luiss']['pts']}pt ({best_st['luiss']['w']}V-{best_st['luiss']['l']}P)")
        return best_st
    else:
        print(f"  ℹ️  Classifica già aggiornata — nessuna modifica")
        return standings


def find_match(scraped, match):
    mh = normalise(match["home"])
    md_str = match["date"]
    for s in scraped:
        sh = normalise(s["home"])
        # Controlla data se disponibile
        if s.get("date") and md_str:
            try:
                md = datetime.strptime(md_str, "%Y-%m-%d").date()
                sd = datetime.strptime(s["date"], "%Y-%m-%d").date()
                if abs((sd - md).days) > 4:
                    continue
            except Exception:
                pass
        # Controlla squadra di casa
        home_ok = (
            sh in mh or mh in sh or
            ("virtus roma" in mh and "virtus" in sh) or
            ("luiss" in mh and "luiss" in sh)
        )
        if home_ok:
            return s
    return None


# ================================================================
# RICERCA URL DA PIÙ FONTI NAZIONALI
# ================================================================

def find_result_urls(serie, last_round):
    """
    Cerca su pianetabasket, playbasket e legapallacanestro
    gli URL delle ultime giornate per il campionato dato.
    Restituisce lista di tuple (sito, url).
    """
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    found = []

    # ── 1. pianetabasket.com ──────────────────────────────────
    pb_home = sources.get("pianetabasket")
    pb_section = sources.get("pb_section", "/serie-b/")
    if pb_home:
        html = fetch(pb_home)
        if html:
            # Cerca link a pagine risultati della stagione corrente
            pat = re.compile(
                r'href=["\'](' + re.escape(pb_section) +
                r'[^"\']*(?:risultati|calendario)[^"\']*2025-26[^"\']*)["\']'
            )
            for m in pat.finditer(html):
                url = "https://www.pianetabasket.com" + m.group(1)
                rnd = _extract_round(url)
                if rnd and rnd > last_round and ("pianetabasket", url) not in found:
                    found.append(("pianetabasket", url))
            # Fallback: qualsiasi URL con 2025-26 e numero ID
            if not [x for x in found if x[0] == "pianetabasket"]:
                pat2 = re.compile(
                    r'href=["\'](' + re.escape(pb_section) + r'[^"\']*2025-26-\d+)["\']'
                )
                for m in pat2.finditer(html):
                    url = "https://www.pianetabasket.com" + m.group(1)
                    if ("risultati" in url or "calendario" in url) and ("pianetabasket", url) not in found:
                        found.append(("pianetabasket", url))
            pb_n = sum(1 for s, _ in found if s == "pianetabasket")
            print(f"  🔍 pianetabasket ({serie}): {pb_n} URL")

    # ── 2. playbasket.it ──────────────────────────────────────
    pp_home = sources.get("playbasket")
    if pp_home:
        html = fetch(pp_home)
        if html:
            pat = re.compile(r'href=["\']([^"\']*playbasket\.it[^"\']*(?:risultati|giornata|tabellino)[^"\']*)["\']')
            pp_n = 0
            for m in pat.finditer(html):
                url = m.group(1)
                if not url.startswith("http"):
                    url = "https://www.playbasket.it" + url
                rnd = _extract_round(url)
                if (rnd is None or rnd > last_round) and ("playbasket", url) not in found:
                    found.append(("playbasket", url))
                    pp_n += 1
            print(f"  🔍 playbasket ({serie}): {pp_n} URL")

    # ── 3. legapallacanestro.com ──────────────────────────────
    lnp_home = sources.get("lnp")
    if lnp_home:
        html = fetch(lnp_home)
        if html:
            pat = re.compile(r'href=["\']([^"\']*legapallacanestro\.com[^"\']*(?:calendario|risultati)[^"\']*)["\']')
            lnp_n = 0
            for m in pat.finditer(html):
                url = m.group(1)
                if not url.startswith("http"):
                    url = "https://www.legapallacanestro.com" + url
                if ("lnp", url) not in found:
                    found.append(("lnp", url))
                    lnp_n += 1
            print(f"  🔍 legapallacanestro ({serie}): {lnp_n} URL")

    print(f"  🔍 Totale URL ({serie}): {len(found)}")
    return found


def _extract_round(url):
    """Estrae il numero di giornata dall'URL se presente."""
    m = re.search(r"-(\d+)-giornata-", url)
    return int(m.group(1)) if m else None


def scrape_urls(url_list, girone_check=None):
    """Scarica e analizza gli URL trovati, restituisce tutti i risultati."""
    all_results = []
    done_rounds = set()
    for source, url in url_list:
        rnd = _extract_round(url)
        if rnd and rnd in done_rounds:
            continue
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        if girone_check and girone_check not in html.lower():
            continue
        scraped = parse_results(html)
        if scraped:
            print(f"  ✅ {source} G{rnd or '?'}: {len(scraped)} risultati")
            all_results.extend(scraped)
            if rnd:
                done_rounds.add(rnd)
    return all_results


# ================================================================
# IN STAGIONE — aggiorna risultati e orari
# ================================================================

def update_in_season(matches, config, standings):
    today = date.today()
    rounds_done = [m["round"] for m in matches
                   if m.get("sh") is not None and m.get("phase") == "regular"]
    last_round = max(rounds_done) if rounds_done else 0
    print(f"  Ultima giornata con risultati: {last_round}")

    # Determina le serie in gioco
    serie_set = set(
        config["teams"][t]["serie"]
        for t in config["teams"]
    )

    all_scraped = []
    for serie in serie_set:
        sources_cfg = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
        girone_check = sources_cfg.get("girone_check")
        print(f"\n  📡 Ricerca risultati per {serie}...")

        # Metodo 1: URL reali dalle homepage
        url_list = find_result_urls(serie, last_round)
        scraped_this = scrape_urls(url_list, girone_check)
        all_scraped.extend(scraped_this)

        # Aggiorna classifica dalle stesse pagine già scaricate
        for source, url in url_list:
            html = fetch(url)
            if not html or len(html) < 1000:
                continue
            if girone_check and girone_check not in html.lower():
                continue
            aliases_v = config["teams"]["virtus"]["name_aliases"]
            aliases_l = config["teams"]["luiss"]["name_aliases"]
            new_st = parse_standings(html, aliases_v, aliases_l)
            if new_st:
                if new_st["virtus"]["pts"] >= standings.get("virtus", {}).get("pts", 0):
                    standings.update(new_st)
                    print(f"  📊 Classifica da risultati: Virtus {new_st['virtus']['pos']}° {new_st['virtus']['pts']}pt | LUISS {new_st['luiss']['pos']}° {new_st['luiss']['pts']}pt")
                    break

        # Metodo 2: fallback con ID stimati su pianetabasket
        if serie in ("B Nazionale", "B Interregionale"):
            for rnd in range(max(1, last_round + 1), 39):
                # Salta se abbiamo già trovato risultati per questa giornata
                already = any(
                    find_match(all_scraped, m)
                    for m in matches
                    if m.get("round") == rnd and m.get("sh") is None and isPastMatch(m, today)
                )
                if already:
                    continue
                base_id = 356237 + (rnd - 31) * 1500
                found_rnd = False
                for delta in range(-800, 801, 100):
                    if found_rnd:
                        break
                    cid = base_id + delta
                    suffixes = [
                        "classifiche", "sabato-classifiche",
                        "domenica-classifiche", "le-gare-di-lunedi-classifiche",
                        "le-gare-di-venerdi-classifiche"
                    ]
                    for suf in suffixes:
                        url = (
                            f"https://www.pianetabasket.com/serie-b/"
                            f"serie-b-nazionale-calendario-risultati-{suf}-"
                            f"{rnd}-giornata-2025-26-{cid}"
                        )
                        html = fetch(url)
                        if not html or len(html) < 1000:
                            continue
                        if girone_check and girone_check not in html.lower():
                            continue
                        scraped = parse_results(html)
                        if scraped:
                            print(f"  ✅ Fallback G{rnd}: {len(scraped)} risultati")
                            all_scraped.extend(scraped)
                            found_rnd = True
                            break

    # Applica risultati alle partite
    updated = 0
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if md < today and m.get("sh") is None:
            found = find_match(all_scraped, m)
            if found:
                m["sh"] = found["sh"]
                m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  ✅ {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1
        # Aggiorna orario partite future
        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print(f"  🕐 {m['home']} vs {m['away']}: orario → {found['time']}")
                m["time"] = found["time"]
                updated += 1

    return updated


def isPastMatch(m, today):
    try:
        return datetime.strptime(m["date"], "%Y-%m-%d").date() < today
    except Exception:
        return False


# ================================================================
# FUORI STAGIONE — cerca nuovo calendario su LNP
# ================================================================

def search_new_calendar(next_season, config):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    slug = next_season

    # Prova tutti i PDF LNP per tutte le serie
    pdf_templates = [
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._a_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_lba_{slug}.pdf",
    ]
    serie_names = ["B Nazionale", "B Nazionale", "A2", "LBA"]

    for pdf_url, serie in zip(pdf_templates, serie_names):
        html = fetch(pdf_url)
        if not html or len(html) < 500:
            continue
        hl = html.lower()
        for team_key, team_cfg in config["teams"].items():
            for alias in team_cfg["name_aliases"]:
                if alias in hl:
                    print(f"  📄 Trovato {team_cfg['name']} in {serie} — {pdf_url}")
                    new_matches = parse_pdf(html, slug)
                    if new_matches:
                        config["teams"][team_key]["serie"] = serie
                        return new_matches, slug

    # Prova anche playbasket e pianetabasket per la nuova stagione
    check_urls = [
        "https://www.legapallacanestro.com/serie/4/calendario",
        "https://www.legapallacanestro.com/serie/1/calendario",
        "https://www.pianetabasket.com/serie-b/",
        "https://www.pianetabasket.com/serie-a2/",
    ]
    for url in check_urls:
        html = fetch(url)
        if html and slug in html:
            for team_cfg in config["teams"].values():
                for alias in team_cfg["name_aliases"]:
                    if alias in html.lower():
                        print(f"  🌐 Nuova stagione {slug} rilevata su {url}")
                        return None, slug

    print(f"  ℹ️  Calendario {next_season} non ancora disponibile")
    return None, None


def parse_pdf(text, slug):
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
            "id": f"{team[0]}{rnd:02d}",
            "team": team, "phase": "regular", "round": rnd,
            "date": f"{yyyy}-{mm}-{dd}", "time": "",
            "home": home, "away": away, "sh": None, "sa": None,
        })
    return new_matches


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v3 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches   = current.get("matches", [dict(m) for m in BASE_MATCHES])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config    = current.get("config", CONFIG)
        print(f"📂 data.json caricato — {len(matches)} partite, stagione {config.get('season','?')}")
    else:
        matches   = [dict(m) for m in BASE_MATCHES]
        standings = dict(BASE_STANDINGS)
        config    = CONFIG
        print("📂 Primo avvio — uso dati base")

    today       = date.today()
    next_season = config.get("next_season", "2026-27")
    all_dates   = [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in matches]
    season_end  = max(all_dates) if all_dates else date(2026, 6, 30)
    in_season   = today <= season_end + timedelta(days=30)

    total_updated = 0

    if in_season:
        print(f"\n📅 Modalità: IN STAGIONE")
        serie_v = config["teams"]["virtus"]["serie"]
        serie_l = config["teams"]["luiss"]["serie"]
        print(f"   Virtus: {serie_v} | LUISS: {serie_l}")
        total_updated = update_in_season(matches, config, standings)
        print(f"\n📝 Aggiornamenti: {total_updated}")
        # Recupera classifica da più fonti nazionali
        print("\n  🏆 Aggiornamento classifica da più siti...")
        standings = fetch_all_standings(config, standings)
    else:
        print(f"\n💤 Modalità: FUORI STAGIONE — cerco {next_season}")
        new_matches, found = search_new_calendar(next_season, config)
        if new_matches and found:
            print(f"🆕 Nuovo calendario {found} trovato!")
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
            print(f"ℹ️  Stagione {found} rilevata — calendario non ancora scaricabile")
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

    print(f"💾 data.json salvato — {len(matches)} partite")
    print("✅ Completato!\n")
    return total_updated


if __name__ == "__main__":
    main()

