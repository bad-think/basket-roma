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
