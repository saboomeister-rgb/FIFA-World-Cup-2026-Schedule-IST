import requests
import re
import sys

# Map API team names to names used in index.html
NAME_MAP = {
    "United States": "USA",
    "Turkey": "Türkiye",
    "Bosnia-Herzegovina": "Bosnia & Herz.",
    "Bosnia and Herzegovina": "Bosnia & Herz.",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Korea Republic": "South Korea",
    "Czech Republic": "Czechia",
}

def norm(name):
    return NAME_MAP.get(name, name)

def fetch_openfootball():
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_worldcup26():
    """Fallback: free API, no key required"""
    url = "https://worldcup26.ir/get/games"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def parse_openfootball(data):
    results = {}
    # openfootball uses a flat "matches" list — team names are plain strings
    for m in data.get("matches", []):
        s1 = m.get("score1")
        s2 = m.get("score2")
        if s1 is None or s2 is None:
            continue  # Not played yet
        t1 = norm(str(m.get("team1", "")))
        t2 = norm(str(m.get("team2", "")))
        if not t1 or not t2:
            continue
        s1, s2 = int(s1), int(s2)
        if s1 > s2:
            result = f"{t1} {s1}\u2013{s2}"
        elif s2 > s1:
            result = f"{t2} {s2}\u2013{s1}"
        else:
            result = f"{s1}\u2013{s2} Draw"
        results[(t1, t2)] = result
    return results

def parse_worldcup26(data):
    results = {}
    games = data if isinstance(data, list) else data.get("games", data.get("data", []))
    for m in games:
        s1 = m.get("score1") or m.get("homeScore") or m.get("home_score") or m.get("goals_home")
        s2 = m.get("score2") or m.get("awayScore") or m.get("away_score") or m.get("goals_away")
        if s1 is None or s2 is None:
            continue
        t1 = norm(str(m.get("team1") or m.get("home") or m.get("home_team") or ""))
        t2 = norm(str(m.get("team2") or m.get("away") or m.get("away_team") or ""))
        if not t1 or not t2:
            continue
        s1, s2 = int(s1), int(s2)
        if s1 > s2:
            result = f"{t1} {s1}\u2013{s2}"
        elif s2 > s1:
            result = f"{t2} {s2}\u2013{s1}"
        else:
            result = f"{s1}\u2013{s2} Draw"
        results[(t1, t2)] = result
    return results

def update_html(results):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    original = html
    updated = 0

    for (t1, t2), result in results.items():
        pattern = (
            r'(\["(?:group|ko|final)","[^"]*",'
            + r'"' + re.escape(t1) + r'",'
            + r'"' + re.escape(t2) + r'",'
            + r'"[^"]*","[^"]*","[^"]*",)"[^"]*"(\])'
        )
        replacement = r'\g<1>"' + result + r'"\2'
        new_html = re.sub(pattern, replacement, html)
        if new_html != html:
            html = new_html
            updated += 1

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Done — updated {updated} match results in index.html")
    else:
        print("No changes — results already current or no completed matches found in source")

def main():
    results = {}

    # Primary: openfootball (free, no API key, updated daily)
    try:
        data = fetch_openfootball()
        results = parse_openfootball(data)
        print(f"openfootball: {len(results)} completed matches found")
    except Exception as e:
        print(f"openfootball fetch failed: {e}")

    # Fallback if primary returns nothing
    if not results:
        try:
            data = fetch_worldcup26()
            results = parse_worldcup26(data)
            print(f"worldcup26.ir fallback: {len(results)} completed matches found")
        except Exception as e:
            print(f"worldcup26.ir fallback failed: {e}")

    if not results:
        print("No results from any source — nothing to update")
        sys.exit(0)

    update_html(results)

if __name__ == "__main__":
    main()
