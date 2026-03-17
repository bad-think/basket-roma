#!/usr/bin/env python3
"""
update_data.py — Aggiornamento automatico Roma Basket Casa
Gira ogni notte via GitHub Actions.

IN STAGIONE:    aggiorna risultati, orari, classifica da pianetabasket.com
FUORI STAGIONE: cerca il nuovo calendario LNP per la stagione successiva
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE — aggiorna qui a inizio di ogni stagione
# ================================================================
CONFIG = {
    "season": "2025-26",
    "next_season": "2026-27",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": ["virtus gvm roma", "virtus roma", "virtus gvm roma 1960"],
            "serie": "B Nazionale", "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss"],
            "serie": "B Nazionale", "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        }
    }
}

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
    {"id":"v32","team":"virtus","phase":"regular","round":32,"date":"2026-03-21","time":"20:00","home":"Virtus GVM Roma","away":"Ristopro Fabriano","sh":None,"sa":None},
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
    "virtus": {"pos": 3, "pts": 46, "w": 23, "l": 7},
    "luiss":  {"pos": 5, "pts": 38, "w": 19, "l": 11},
}

# ================================================================
# UTILITY
# ================================================================

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/2.0)",
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
        ("virtus gvm roma 1960","virtus roma"), ("virtus gvm roma","virtus roma"),
        ("luiss roma","luiss"), (r"consorzio.*?quarrata","quarrata"),
        (r"paperdi juve\S*","juvecaserta"), ("malvin psa basket casoria","casoria"),
        ("psa basket casoria","casoria"), ("verodol cbd pielle livorno","pielle livorno"),
        ("up andrea costa imola","andrea costa"), ("benacquista assicurazioni latina","latina"),
        ("allianz pazienza san severo","san severo"), ("umana san giobbe chiusi","chiusi"),
        ("general contractor jesi","jesi"), (r"solbat.*piombino","piombino"),
        (r"orasì ravenna|orasi ravenna","ravenna"), (r"power basket nocera\S*","nocera"),
        (r"adamant ferrara\S*","ferrara"), (r"virtus (?:pallacanestro )?imola","v.imola"),
        (r"ristopro (?:janus )?fabriano","fabriano"), ("raggisolaris faenza","faenza"),
    ]:
        s = re.sub(old, new, s)
    return re.sub(r"\s+", " ", s).strip()

def parse_results(html):
    results = []
    plain = re.sub(r"&#x27;","'", html)
    plain = re.sub(r"&amp;","&", plain)
    plain = re.sub(r"<[^>]+>"," ", plain)
    plain = re.sub(r"\s+"," ", plain)
    pat = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.]+?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.]+?)\s+"
        r"(\d{2,3})-(\d{2,3})(?:\s|$)"
    )
    for m in pat.finditer(plain):
        dr,t,h,a,sh,sa = m.groups()
        dd,mm,yyyy = dr.split("/")
        results.append({
            "date": f"{yyyy}-{mm}-{dd}",
            "time": t,
            "home": h.strip(),
            "away": a.strip(),
            "sh": int(sh),
            "sa": int(sa)
        })
    return results

def find_match(scraped, match):
    mh = normalise(match["home"])
    md = datetime.strptime(match["date"], "%Y-%m-%d").date()
    for s in scraped:
        sh = normalise(s["home"])
        sd = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if abs((sd - md).days) > 4:
            continue
        if (sh in mh or mh in sh or
            ("virtus roma" in mh and "virtus" in sh) or
            ("luiss" in mh and "luiss" in sh)):
            return s
    return None

# ================================================================
# IN STAGIONE — scarica risultati da pianetabasket.com
# ================================================================

def update_in_season(matches):
    today = date.today()

    # Ultima giornata con risultati noti
    rounds_done = [m["round"] for m in matches
                   if m.get("sh") is not None and m.get("phase") == "regular"]
    last_round = max(rounds_done) if rounds_done else 0
    print(f"  Ultima giornata con risultati: {last_round}")

    all_scraped = []
    found_rounds = set()
    seen = set()

    # Cerca le giornate dalla successiva fino alla 38
    for rnd in range(max(1, last_round), 39):
        if rnd in found_rounds:
            continue
        base_id = 356237 + (rnd - 31) * 1500
        urls = []
        for delta in range(-600, 601, 100):
            cid = base_id + delta
            urls += [
                f"https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-classifiche-{rnd}-giornata-2025-26-{cid}",
                f"https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-le-gare-di-lunedi-classifiche-{rnd}-giornata-2025-26-{cid}",
                f"https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-le-gare-di-domenica-classifiche-{rnd}-giornata-2025-26-{cid}",
            ]

        for url in urls:
            if url in seen or rnd in found_rounds:
                break
            seen.add(url)
            html = fetch(url)
            if not html or len(html) < 1000:
                continue
            if "girone b" not in html.lower():
                continue
            scraped = parse_results(html)
            if scraped:
                print(f"  ✅ Giornata {rnd}: {len(scraped)} risultati trovati")
                all_scraped.extend(scraped)
                found_rounds.add(rnd)
                break

    # Applica aggiornamenti
    updated = 0
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()

        # Risultato partita passata senza punteggio
        if md < today and m.get("sh") is None:
            found = find_match(all_scraped, m)
            if found:
                m["sh"] = found["sh"]
                m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  ✅ {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1

        # Orario partita futura cambiato
        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print(f"  🕐 {m['home']} vs {m['away']}: orario → {found['time']}")
                m["time"] = found["time"]
                updated += 1

    return updated

# ================================================================
# FUORI STAGIONE — cerca nuovo calendario LNP
# ================================================================

def search_new_calendar(next_season):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    slug = next_season  # es. "2026-27"

    pdf_urls = [
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._a_{slug}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{slug}.pdf",
    ]

    for url in pdf_urls:
        html = fetch(url)
        if html and len(html) > 500 and ("virtus" in html.lower() or "luiss" in html.lower()):
            print(f"  📄 PDF trovato: {url}")
            new_matches = parse_pdf(html, slug)
            if new_matches:
                return new_matches, slug

    # Controlla pagina calendario LNP web
    for url in [
        "https://www.legapallacanestro.com/serie/4/calendario",
        "https://www.legapallacanestro.com/serie/1/calendario",
    ]:
        html = fetch(url)
        if html and slug in html:
            print(f"  🌐 Nuova stagione rilevata su LNP")
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
    print(f"\n🏀 Roma Basket Updater — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches   = current.get("matches", [dict(m) for m in BASE_MATCHES])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config    = current.get("config", CONFIG)
        print(f"📂 data.json caricato — {len(matches)} partite")
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
        total_updated = update_in_season(matches)
        print(f"📝 Aggiornamenti: {total_updated}")
    else:
        print(f"\n💤 Modalità: FUORI STAGIONE — cerco {next_season}")
        new_matches, found = search_new_calendar(next_season)
        if new_matches and found:
            print(f"🆕 Nuovo calendario {found} trovato!")
            matches   = new_matches
            standings = {"virtus":{"pos":0,"pts":0,"w":0,"l":0},
                         "luiss": {"pos":0,"pts":0,"w":0,"l":0}}
            yr = int(found[:4])
            config["season"]      = found
            config["next_season"] = f"{yr+1}-{str(yr+2)[2:]}"
            total_updated = len(new_matches)
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
