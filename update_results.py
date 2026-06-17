import requests
import re
import sys

# Map ESPN/API team names → names used in index.html
NAME_MAP = {
    "United States": "USA",
    "Turkey": "Türkiye",
    "Bosnia and Herzegovina": "Bosnia & Herz.",
    "Bosnia-Herzegovina": "Bosnia & Herz.",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "DR Congo": "DR Congo",
    "Congo, DR": "DR Congo",
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Czech Republic": "Czechia",
    "Czechia": "Czechia",
    "Türkiye": "Türkiye",
    "New Zealand": "New Zealand",
    "Saudi Arabia": "Saudi Arabia",
    "Cape Verde": "Cape Verde",
}

def norm(name):
    return NAME_MAP.get(name, name)

def fetch_espn():
    """
    ESPN unofficial API — no key needed, reliable, live scores.
    Fetches the entire WC 2026 tournament in one call.
    """
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        "fifa.world/scoreboard?dates=20260611-20260720&limit=150"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_espn(data):
    results = {}
    events = data.get("events", [])
    print(f"ESPN: {len(events)} total events found")

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]

        # Only process completed matches
        status = comp.get("status", {})
        completed = status.get("type", {}).get("completed", False)
        if not completed:
            continue

        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        # ESPN labels home/away — find each
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        t1_name = norm(home.get("team", {}).get("displayName", ""))
        t2_name = norm(away.get("team", {}).get("displayName", ""))
        
        try:
            s1 = int(home.get("score", -1))
            s2 = int(away.get("score", -1))
        except (ValueError, TypeError):
            continue

        if s1 < 0 or s2 < 0 or not t1_name or not t2_name:
            continue

        if s1 > s2:
            result = f"{t1_name} {s1}\u2013{s2}"
        elif s2 > s1:
            result = f"{t2_name} {s2}\u2013{s1}"
        else:
            result = f"{s1}\u2013{s2} Draw"

        results[(t1_name, t2_name)] = result
        print(f"  {t1_name} {s1}-{s2} {t2_name}")

    return results

def update_html(results):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    original = html
    updated = 0

    for (t1, t2), result in results.items():
        # Match the entry in the matches array and update the result field
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
        print(f"\nDone — updated {updated} match results in index.html")
    else:
        print(f"\nNo HTML changes — {len(results)} results found but none matched entries (check team name mapping)")

def main():
    try:
        data = fetch_espn()
        results = parse_espn(data)
        print(f"\n{len(results)} completed matches parsed")
    except Exception as e:
        print(f"ESPN fetch failed: {e}")
        sys.exit(0)  # Don't break the action, just skip this run

    if not results:
        print("No completed matches yet — nothing to update")
        sys.exit(0)

    update_html(results)

if __name__ == "__main__":
    main()
