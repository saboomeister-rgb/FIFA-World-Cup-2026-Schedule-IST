import requests
import re
import sys

# Map API team names to names used in index.html
NAME_MAP = {
    "United States": "USA",
    "Turkey": "Türkiye",
    "Bosnia-Herzegovina": "Bosnia & Herz.",
    "Bosnia and Herzegovina": "Bosnia & Herz.",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Korea Republic": "South Korea",
    "Czech Republic": "Czechia",
    "Iran": "Iran",
}

def norm(name):
    return NAME_MAP.get(name, name)

def fetch_results():
    """Fetch from openfootball — free, no API key, covers WC 2026"""
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Fetch failed: {e}")
        sys.exit(0)  # Don't break the action — just skip this run

def parse_results(data):
    results = {}
    for rnd in data.get("rounds", []):
        for m in rnd.get("matches", []):
            s1 = m.get("score1")
            s2 = m.get("score2")
            if s1 is None or s2 is None:
                continue  # Match not played yet
            t1 = norm(m["team1"]["name"])
            t2 = norm(m["team2"]["name"])
            # Use en-dash (–) to match existing format in HTML
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
        # Match the line in the matches array and replace the result field
        pattern = (
            r'(\["(?:group|ko|final)","[^"]*",'
            + r'"' + re.escape(t1) + r'",'
            + r'"' + re.escape(t2) + r'",'
            + r'"[^"]*","[^"]*","[^"]*",)"[^"]*"(\])'
        )
        replacement = r'\g<1>"' + result.replace('\\', '\\\\') + r'"\2'
        new_html = re.sub(pattern, replacement, html)
        if new_html != html:
            html = new_html
            updated += 1

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Done — updated {updated} match results in index.html")
    else:
        print("No changes — all results already current or no new results")

def main():
    data = fetch_results()
    results = parse_results(data)
    print(f"Found {len(results)} completed matches in source data")
    update_html(results)

if __name__ == "__main__":
    main()
