#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico
Versione definitiva — nessuna modifica necessaria per il resto della stagione.

Fonti risultati e classifica:
  1. pianetabasket.com — principale (URL reali noti + ricerca homepage)
  2. playbasket.it      — backup nazionale
  3. legapallacanestro.com — ufficiale LNP

Campionati supportati (auto-rilevamento per stagioni future):
  Serie B Nazionale, Serie A2, LBA, Serie B Interregionale
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE BASE
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
# URL NOTI DI PIANETABASKET PER OGNI GIORNATA (Girone B 2025-26)
# Aggiornati con gli URL reali trovati durante la stagione
# ================================================================
KNOWN_URLS = {
    31: [
        "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-le-gare-di-lunedi-classifiche-31-giornata-2025-26-356237",
        "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-domenica-classifiche-31-giornata-2025-26-356237",
    ],
    32: [
        "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-32-giornata-2025-26-357140",
        "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-classifiche-32-giornata-2025-26-357140",
        "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-venerdi-classifiche-32-giornata-2025-26-357140",
    ],
    # Le giornate 33-38 verranno trovate automaticamente dalla homepage
}

# Range ID stimati per le giornate future (base + delta)
# ID reale G32 = 357140. Ogni giornata circa +800-1500 ID
ROUND_BASE_IDS = {
    33: 358000, 34: 359000, 35: 360000,
    36: 361000, 37: 362000, 38: 363000,
}

LEAGUE_SOURCES = {
    "B Nazionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
        "playbasket":   "https://www.playbasket.it/serie-b",
        "lnp":          "https://www.legapallacanestro.com/serie/4/classifica",
        "girone_check": "girone b",
    },
    "A2": {
        "pb_home":      "https://www.pianetabasket.com/serie-a2/",
        "pb_section":   "/serie-a2/",
        "playbasket":   "https://www.playbasket.it/serie-a2",
        "lnp":          "https://www.legapallacanestro.com/serie/1/classifica",
        "girone_check": None,
    },
    "LBA": {
        "pb_home":      "https://www.pianetabasket.com/legabasket-serie-a/",
        "pb_section":   "/legabasket-serie-a/",
        "playbasket":   "https://www.playbasket.it/serie-a",
        "lnp":          None,
        "girone_check": None,
    },
    "B Interregionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
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
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/4.0)",
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
        ("tema sinergie faenza", "faenza"),
        ("consultinvest loreto pesaro", "loreto pesaro"),
        ("loreto basket pesaro", "loreto pesaro"),
    ]:
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()


def parse_results(html):
    """Estrae risultati dal testo HTML di pianetabasket (e siti simili)."""
    results = []
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
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
                "time": t, "home": h, "away": a,
                "sh": int(sh), "sa": int(sa)
            })
        except Exception:
            continue
    return results


def parse_standings_from_html(html, aliases_v, aliases_l):
    """
    Estrae classifica Girone B da HTML pianetabasket.
    Formato: 'NomeSquadra PP VV-LL'
    Prende sempre la classifica più aggiornata presente nella pagina.
    """
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    # Cerca TUTTI i blocchi classifica Girone B nella pagina
    # e prende quello con i punti più alti (= più recente)
    best = None
    best_total = 0

    for idx_start in [m.start() for m in re.finditer(r"[Cc]lassifica\s+girone\s+[Bb]", plain)]:
        block = plain[idx_start:idx_start + 2500]
        # Taglia al prossimo blocco Girone A o NOTA
        for stop in ["classifica girone a", "classifica girone a", "nota -"]:
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
                candidate["luiss"]  = {"pos": pos, "pts": pts, "w": w, "l": l}
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
    md_str = match["date"]
    for s in scraped:
        sh_n = normalise(s["home"])
        if s.get("date") and md_str:
            try:
                md = datetime.strptime(md_str, "%Y-%m-%d").date()
                sd = datetime.strptime(s["date"], "%Y-%m-%d").date()
                if abs((sd - md).days) > 4:
                    continue
            except Exception:
                pass
        home_ok = (
            sh_n in mh or mh in sh_n or
            ("virtus roma" in mh and "virtus" in sh_n) or
            ("luiss" in mh and "luiss" in sh_n)
        )
        if home_ok:
            return s
    return None


# ================================================================
# RACCOLTA URL RISULTATI
# ================================================================

def get_urls_for_round(rnd):
    """Restituisce gli URL da provare per una data giornata."""
    urls = []
    # 1. URL noti (verificati durante la stagione)
    if rnd in KNOWN_URLS:
        urls.extend(KNOWN_URLS[rnd])
    # 2. Stima da base_id
    base_id = ROUND_BASE_IDS.get(rnd, 356237 + (rnd - 31) * 1500)
    suffixes = [
        "classifiche", "sabato-classifiche", "domenica-classifiche",
        "venerdi-classifiche", "le-gare-di-lunedi-classifiche",
        "le-gare-di-mercoledi-classifiche"
    ]
    for delta in range(-800, 801, 100):
        cid = base_id + delta
        for suf in suffixes:
            url = (
                f"https://www.pianetabasket.com/serie-b/"
                f"serie-b-nazionale-calendario-risultati-{suf}-"
                f"{rnd}-giornata-2025-26-{cid}"
            )
            if url not in urls:
                urls.append(url)
    return urls


def find_urls_from_homepage(serie):
    """Cerca gli URL delle ultime giornate dalla homepage di pianetabasket."""
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pb_home = sources.get("pb_home", "https://www.pianetabasket.com/serie-b/")
    pb_section = sources.get("pb_section", "/serie-b/")
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
        if url not in found:
            found.append(url)
    # Fallback: qualsiasi URL con ID numerico
    if not found:
        pat2 = re.compile(
            r'href=["\'](' + re.escape(pb_section) + r'[^"\']*2025-26-\d+)["\']'
        )
        for m in pat2.finditer(html):
            url = "https://www.pianetabasket.com" + m.group(1)
            if url not in found:
                found.append(url)
    print(f"  🔍 Homepage pianetabasket: {len(found)} URL trovati")
    return found


def find_urls_from_playbasket(serie):
    """Cerca URL delle ultime giornate su playbasket.it."""
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pp_home = sources.get("playbasket")
    if not pp_home:
        return []
    found = []
    html = fetch(pp_home)
    if not html:
        return []
    pat = re.compile(
        r'href=["\']([^"\']*playbasket\.it[^"\']*(?:risultati|giornata)[^"\']*)["\']'
    )
    for m in pat.finditer(html):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://www.playbasket.it" + url
        if url not in found:
            found.append(url)
    print(f"  🔍 playbasket: {len(found)} URL trovati")
    return found


# ================================================================
# AGGIORNAMENTO CLASSIFICA DA PIÙ FONTI
# ================================================================

def update_standings_multi(standings, config, scraped_htmls):
    """
    Aggiorna la classifica cercando su più fonti.
    Prende sempre il dato con punteggio totale più alto (= più recente).
    """
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma", "virtus gvm roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])

    candidates = []

    # 1. Da pagine risultati già scaricate
    for label, html in scraped_htmls:
        if not html:
            continue
        st = parse_standings_from_html(html, aliases_v, aliases_l)
        if st:
            candidates.append((label, st))

    # 2. Pagina classifica dedicata pianetabasket
    pb_class_url = (
        sources.get("pb_home", "").rstrip("/") +
        "/classifica-serie-b-nazionale-girone-b-2025-26"
    )
    html = fetch(pb_class_url)
    if html:
        st = parse_standings_from_html(html, aliases_v, aliases_l)
        if st:
            candidates.append(("pb-classifica", st))

    # 3. LNP ufficiale
    lnp_url = sources.get("lnp")
    if lnp_url:
        html = fetch(lnp_url)
        if html:
            st = parse_standings_from_html(html, aliases_v, aliases_l)
            if st:
                candidates.append(("lnp", st))

    # 4. playbasket
    pp_url = sources.get("playbasket")
    if pp_url:
        for suffix in ["/classifica", ""]:
            html = fetch(pp_url + suffix)
            if html:
                st = parse_standings_from_html(html, aliases_v, aliases_l)
                if st:
                    candidates.append(("playbasket", st))
                    break

    if not candidates:
        print("  ⚠️  Nessuna classifica trovata")
        return standings

    # Prendi il candidato con punteggio totale più alto
    best_label, best = max(
        candidates,
        key=lambda x: x[1]["virtus"]["pts"] + x[1]["luiss"]["pts"]
    )
    current_total = standings.get("virtus", {}).get("pts", 0) + standings.get("luiss", {}).get("pts", 0)
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
    else:
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
    scraped_htmls = []  # (label, html) per aggiornamento classifica

    # 1. URL dalla homepage di pianetabasket
    home_urls = find_urls_from_homepage(serie)
    for url in home_urls:
        rnd_m = re.search(r"-(\d+)-giornata-", url)
        rnd = int(rnd_m.group(1)) if rnd_m else None
        if rnd and rnd <= last_round:
            continue
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        if girone_check and girone_check not in html.lower():
            continue
        scraped = parse_results(html)
        if scraped:
            print(f"  ✅ pb-homepage G{rnd or '?'}: {len(scraped)} risultati")
            all_scraped.extend(scraped)
            scraped_htmls.append((f"pb-G{rnd}", html))

    # 2. URL noti + ID stimati per le giornate future
    found_rounds = {
        int(re.search(r"-(\d+)-giornata-", u).group(1))
        for _, h in scraped_htmls
        for u in [_]
        if re.search(r"-(\d+)-giornata-", u)
    }
    for rnd in range(last_round + 1, 39):
        if rnd in found_rounds:
            continue
        for url in get_urls_for_round(rnd):
            html = fetch(url)
            if not html or len(html) < 1000:
                continue
            if girone_check and girone_check not in html.lower():
                continue
            scraped = parse_results(html)
            if scraped:
                print(f"  ✅ pb-fallback G{rnd}: {len(scraped)} risultati")
                all_scraped.extend(scraped)
                scraped_htmls.append((f"pb-G{rnd}", html))
                found_rounds.add(rnd)
                break

    # 3. playbasket come backup
    pp_urls = find_urls_from_playbasket(serie)
    for url in pp_urls:
        rnd_m = re.search(r"-(\d+)-giornata-", url)
        rnd = int(rnd_m.group(1)) if rnd_m else None
        if rnd and (rnd <= last_round or rnd in found_rounds):
            continue
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        scraped = parse_results(html)
        if scraped:
            print(f"  ✅ playbasket G{rnd or '?'}: {len(scraped)} risultati")
            all_scraped.extend(scraped)
            scraped_htmls.append((f"pp-G{rnd}", html))

    # Applica risultati
    updated = 0
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if md < today and m.get("sh") is None:
            found = find_match(all_scraped, m)
            if found:
                m["sh"] = found["sh"]; m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  ✅ {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1
        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print(f"  🕐 {m['home']} vs {m['away']}: orario → {found['time']}")
                m["time"] = found["time"]
                updated += 1

    # Aggiorna classifica da più fonti
    print("\n  🏆 Aggiornamento classifica...")
    standings = update_standings_multi(standings, config, scraped_htmls)

    return updated, standings


# ================================================================
# FUORI STAGIONE
# ================================================================

def search_new_calendar(next_season, config):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    slug = next_season
    pdf_urls = [
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._a_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_lba_{slug}.pdf",
    ]
    serie_map = ["B Nazionale", "B Nazionale", "A2", "LBA"]

    for pdf_url, serie in zip(pdf_urls, serie_map):
        html = fetch(pdf_url)
        if not html or len(html) < 500:
            continue
        hl = html.lower()
        for team_key, team_cfg in config["teams"].items():
            for alias in team_cfg.get("name_aliases", []):
                if alias in hl:
                    print(f"  📄 Trovato {team_cfg['name']} in {serie}")
                    new_matches = parse_pdf(html)
                    if new_matches:
                        config["teams"][team_key]["serie"] = serie
                        return new_matches, slug

    for url in [
        "https://www.legapallacanestro.com/serie/4/calendario",
        "https://www.legapallacanestro.com/serie/1/calendario",
        "https://www.pianetabasket.com/serie-b/",
        "https://www.pianetabasket.com/serie-a2/",
    ]:
        html = fetch(url)
        if html and slug in html:
            for team_cfg in config["teams"].values():
                for alias in team_cfg.get("name_aliases", []):
                    if alias in html.lower():
                        print(f"  🌐 Nuova stagione {slug} su {url}")
                        return None, slug

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
    print(f"\n🏀 Roma Basket Updater v4 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches   = current.get("matches", [dict(m) for m in BASE_MATCHES])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config    = current.get("config", CONFIG)
        # Retrocompatibilità: aggiunge campi mancanti senza sovrascrivere
        for team_key, team_default in CONFIG["teams"].items():
            if team_key not in config.get("teams", {}):
                config.setdefault("teams", {})[team_key] = team_default
            else:
                for field, val in team_default.items():
                    config["teams"][team_key].setdefault(field, val)
        config.setdefault("next_season", CONFIG["next_season"])
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
        print(f"\n📅 IN STAGIONE — Virtus: {config['teams']['virtus'].get('serie','?')} | LUISS: {config['teams']['luiss'].get('serie','?')}")
        total_updated, standings = update_in_season(matches, config, standings)
        print(f"\n📝 Risultati aggiornati: {total_updated}")
    else:
        print(f"\n💤 FUORI STAGIONE — cerco {next_season}")
        new_matches, found = search_new_calendar(next_season, config)
        if new_matches and found:
            print(f"🆕 Nuovo calendario {found}!")
            matches = new_matches
            standings = {"virtus":{"pos":0,"pts":0,"w":0,"l":0},"luiss":{"pos":0,"pts":0,"w":0,"l":0}}
            yr = int(found[:4])
            config["season"] = found
            config["next_season"] = f"{yr+1}-{str(yr+2)[2:]}"
            total_updated = len(new_matches)
        elif found:
            print(f"ℹ️  Stagione {found} rilevata — calendario non ancora disponibile")
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

    print(f"\n💾 data.json salvato — {len(matches)} partite")
    print("✅ Completato!\n")
    return total_updated


if __name__ == "__main__":
    main()
