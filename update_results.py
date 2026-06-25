import requests
import re
import sys
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

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

def to_ist_iso(date_str):
    """Convert ESPN UTC date string → IST ISO (YYYY-MM-DDTHH:MM) matching our HTML."""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.astimezone(IST).strftime('%Y-%m-%dT%H:%M')
    except Exception:
        return None

def fetch_espn():
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        "fifa.world/scoreboard?dates=20260611-20260720&limit=150"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_events(data):
    """
    Returns:
      group_results  — list of (ta, tb, sa, sb) for completed group matches
      ko_updates     — list of (ist_iso, ta, tb, result) for all ko/final events
                       where real team names are known (result="" if not yet played)
    """
    events = data.get("events", [])
    print(f"ESPN: {len(events)} total events found")

    group_results = []
    ko_updates = []

    for event in events:
        comps = event.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]

        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        ta = norm(home.get("team", {}).get("displayName", ""))
        tb = norm(away.get("team", {}).get("displayName", ""))

        # Skip if either team is unknown / TBD
        if not ta or not tb or 'TBD' in ta or 'TBD' in tb:
            continue

        ist_iso = to_ist_iso(event.get("date", ""))
        if not ist_iso:
            continue

        if completed:
            try:
                sa = int(home.get("score", -1))
                sb = int(away.get("score", -1))
            except (ValueError, TypeError):
                continue
            if sa < 0 or sb < 0:
                continue

            # Group stage — results list (matched by team name)
            group_results.append((ta, tb, sa, sb))

            # Also add as knockout update (matched by ISO — harmless for group entries)
            ko_updates.append((ist_iso, ta, tb, make_result_str(ta, tb, sa, sb)))
        else:
            # Not yet played — we may still know the teams (e.g. they just qualified)
            ko_updates.append((ist_iso, ta, tb, ""))

    print(f"Parsed: {len(group_results)} completed group results, "
          f"{len(ko_updates)} knockout/final entries with real teams")
    return group_results, ko_updates

def make_result_str(ta, tb, sa, sb):
    if sa > sb:  return f"{ta} {sa}\u2013{sb}"
    elif sb > sa: return f"{tb} {sb}\u2013{sa}"
    else:         return f"{sa}\u2013{sb} Draw"

def make_result(t1, t2, s1, s2):
    if s1 > s2:  return f"{t1} {s1}\u2013{s2}"
    elif s2 > s1: return f"{t2} {s2}\u2013{s1}"
    else:         return f"{s1}\u2013{s2} Draw"

def update_group_html(group_results, html):
    updated = 0
    already = 0
    for (ta, tb, sa, sb) in group_results:
        matched = False
        for (t1, t2, s1, s2) in [(ta, tb, sa, sb), (tb, ta, sb, sa)]:
            result = make_result(t1, t2, s1, s2)
            pat = (
                r'(\["group","[^"]*","' + re.escape(t1) + r'","' + re.escape(t2) + r'",'
                r'"[^"]*","[^"]*","[^"]*",)"[^"]*"(\])'
            )
            new_html = re.sub(pat, r'\g<1>"' + result + r'"\2', html)
            if new_html != html:
                html = new_html; updated += 1; matched = True; break
            # Check if already set correctly
            cur = re.search(
                r'\["group","[^"]*","' + re.escape(t1) + r'","' + re.escape(t2) + r'",'
                r'"[^"]*","[^"]*","[^"]*","([^"]*)"', html)
            if cur and cur.group(1) == result:
                already += 1; matched = True; break
    print(f"  Group: {updated} updated, {already} already correct")
    return html, updated

def update_knockout_html(ko_updates, html):
    """
    For each ko update, match by ISO timestamp and update team names + result.
    This handles both:
      - Newly qualified teams (team names were placeholders, now real)
      - Completed knockout matches (update result)
    """
    updated = 0
    already = 0

    for (ist_iso, ta, tb, result) in ko_updates:
        # ── Check if entry already has correct team names ──────────────────────
        # Try ta/tb order
        existing_pat = (
            r'\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'",'
            r'"' + re.escape(ist_iso) + r'","[^"]*","[^"]*","([^"]*)"'
        )
        m = re.search(existing_pat, html)
        if m:
            if result and m.group(1) != result:
                # Teams correct, just update result
                pat = (
                    r'(\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'",'
                    r'"' + re.escape(ist_iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])'
                )
                new_html = re.sub(pat, r'\g<1>"' + result + r'"\2', html)
                if new_html != html:
                    html = new_html; updated += 1
                    print(f"  KO result updated: {ta} vs {tb} → {result}")
            else:
                already += 1
            continue

        # Try tb/ta reverse order
        rev_pat = (
            r'\["(?:ko|final)","[^"]*","' + re.escape(tb) + r'","' + re.escape(ta) + r'",'
            r'"' + re.escape(ist_iso) + r'"'
        )
        if re.search(rev_pat, html):
            already += 1
            continue

        # ── Team names are still placeholders — replace by ISO match ──────────
        iso_pat = (
            r'(\["(?:ko|final)","[^"]*",)"[^"]*","[^"]*"'
            r'(,"' + re.escape(ist_iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])'
        )
        repl = r'\g<1>"' + ta + '","' + tb + r'"\g<2>"' + (result or "") + r'"\3'
        new_html = re.sub(iso_pat, repl, html)
        if new_html != html:
            html = new_html; updated += 1
            print(f"  KO teams set: {ta} vs {tb} at {ist_iso}"
                  + (f" → {result}" if result else " (upcoming)"))
        # else: ISO not found in HTML (could be a group match entry — silently skip)

    print(f"  Knockout: {updated} updated, {already} already correct")
    return html, updated

def main():
    try:
        data = fetch_espn()
        group_results, ko_updates = parse_events(data)
    except Exception as e:
        print(f"ESPN fetch failed: {e}")
        sys.exit(0)

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    original = html
    total = 0

    html, n = update_group_html(group_results, html)
    total += n
    html, n = update_knockout_html(ko_updates, html)
    total += n

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nDone — {total} updates written to index.html")
    else:
        print(f"\nNo changes — everything already current")

if __name__ == "__main__":
    main()
