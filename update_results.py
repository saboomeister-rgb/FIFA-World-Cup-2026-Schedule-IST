import requests
import re
import sys

# Map ESPN team names → names used in index.html
NAME_MAP = {
    "United States": "USA",
    "Turkey": "Türkiye",
    "Bosnia and Herzegovina": "Bosnia & Herz.",
    "Bosnia-Herzegovina": "Bosnia & Herz.",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Congo, DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "Korea Republic": "South Korea",
    "Czech Republic": "Czechia",
}

def norm(name):
    return NAME_MAP.get(name, name)

def fetch_espn():
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        "fifa.world/scoreboard?dates=20260611-20260720&limit=150"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_espn(data):
    results = []
    events = data.get("events", [])
    print(f"ESPN: {len(events)} total events")
    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]
        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        ta = norm(home.get("team", {}).get("displayName", ""))
        tb = norm(away.get("team", {}).get("displayName", ""))
        try:
            sa = int(home.get("score", -1))
            sb = int(away.get("score", -1))
        except (ValueError, TypeError):
            continue
        if sa < 0 or sb < 0 or not ta or not tb:
            continue
        results.append((ta, tb, sa, sb))
    print(f"{len(results)} completed matches\n")
    return results

def make_result(t1, t2, s1, s2):
    if s1 > s2:
        return f"{t1} {s1}\u2013{s2}"
    elif s2 > s1:
        return f"{t2} {s2}\u2013{s1}"
    else:
        return f"{s1}\u2013{s2} Draw"

def find_current_value(html, t1, t2):
    """Return whatever is currently in the result field for this match."""
    pattern = (
        r'\["(?:group|ko|final)","[^"]*",'
        + r'"' + re.escape(t1) + r'",'
        + r'"' + re.escape(t2) + r'",'
        + r'"[^"]*","[^"]*","[^"]*","([^"]*)"'
        + r'\]'
    )
    m = re.search(pattern, html)
    if m:
        return m.group(1)
    return None

def update_html(matches_data):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    original = html
    updated = 0
    already_correct = 0
    no_match = 0

    for (ta, tb, sa, sb) in matches_data:
        matched = False

        for (t1, t2, s1, s2) in [(ta, tb, sa, sb), (tb, ta, sb, sa)]:
            result = make_result(t1, t2, s1, s2)
            pattern = (
                r'(\["(?:group|ko|final)","[^"]*",'
                + r'"' + re.escape(t1) + r'",'
                + r'"' + re.escape(t2) + r'",'
                + r'"[^"]*","[^"]*","[^"]*",)"[^"]*"(\])'
            )
            replacement = r'\g<1>"' + result + r'"\2'
            new_html = re.sub(pattern, replacement, html)

            if new_html != html:
                # Result changed — write it
                html = new_html
                updated += 1
                matched = True
                print(f"  UPDATED: {t1} vs {t2} -> {result}")
                break
            else:
                # Check if the entry exists but already has the correct value
                current = find_current_value(html, t1, t2)
                if current is not None:
                    if current == result:
                        already_correct += 1
                        matched = True
                        print(f"  OK (already set): {t1} vs {t2} = {result}")
                    else:
                        # Entry found but different value — this shouldn't happen
                        print(f"  MISMATCH: {t1} vs {t2} | in HTML: '{current}' | want: '{result}'")
                        matched = True
                    break

        if not matched:
            no_match += 1
            # Print the raw HTML snippet to diagnose
            snippet_pattern = (
                r'\["(?:group|ko|final)","[^"]*",'
                + r'"' + re.escape(ta) + r'"'
            )
            m = re.search(snippet_pattern, html)
            if m:
                start = max(0, m.start() - 5)
                end = min(len(html), m.end() + 120)
                print(f"  PARTIAL MATCH found for {ta}: ...{repr(html[start:end])}...")
            else:
                print(f"  TRULY NOT FOUND: '{ta}' not in HTML at all")

    print(f"\nSummary: {updated} updated, {already_correct} already correct, {no_match} not found")

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"index.html written with {updated} new results")
    else:
        print("No file changes needed")

def main():
    try:
        data = fetch_espn()
        matches = parse_espn(data)
    except Exception as e:
        print(f"ESPN fetch failed: {e}")
        sys.exit(0)

    if not matches:
        print("No completed matches yet")
        sys.exit(0)

    update_html(matches)

if __name__ == "__main__":
    main()
