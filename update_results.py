import requests
import re
import sys
import json
import time
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
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.astimezone(IST).strftime('%Y-%m-%dT%H:%M')
    except Exception:
        return None

# ── FETCH ──────────────────────────────────────────────────────────────────────

def fetch_scoreboard():
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        "fifa.world/scoreboard?dates=20260611-20260720&limit=150"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_summary(event_id):
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"fifa.world/summary?event={event_id}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

# ── PARSE EVENTS ──────────────────────────────────────────────────────────────

def parse_events(data):
    events = data.get("events", [])
    print(f"ESPN: {len(events)} total events")

    group_results = []
    ko_updates = []
    completed_ids = []

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

        ist_iso = to_ist_iso(event.get("date", ""))
        if not ist_iso:
            continue

        if completed:
            if ta and tb and 'TBD' not in ta and 'TBD' not in tb:
                try:
                    sa = int(home.get("score", -1))
                    sb = int(away.get("score", -1))
                except (ValueError, TypeError):
                    sa = sb = -1
                if sa >= 0 and sb >= 0:
                    group_results.append((ta, tb, sa, sb))
                    ko_updates.append((ist_iso, ta, tb, make_result_str(ta, tb, sa, sb)))
                    completed_ids.append(event.get("id"))
        else:
            if ta and tb and 'TBD' not in ta and 'TBD' not in tb:
                ko_updates.append((ist_iso, ta, tb, ""))

    return group_results, ko_updates, completed_ids

# ── SCORER FETCHING ────────────────────────────────────────────────────────────

def parse_scorers_from_summary(data, team_country):
    """Extract (player_name, country) tuples for each goal from a match summary."""
    goals = []

    # Method 1: scoringPlays at root level
    for play in data.get("scoringPlays", []):
        athletes = play.get("athletesInvolved", [])
        if not athletes:
            continue
        name = athletes[0].get("displayName", "")
        team_id = str(play.get("team", {}).get("id", ""))
        country = team_country.get(team_id, "")
        if name and name != "":
            goals.append((name, country))

    if goals:
        return goals

    # Method 2: competitions[0].details
    comps = data.get("competitions", data.get("header", {}).get("competitions", []))
    details = comps[0].get("details", []) if comps else []

    for detail in details:
        type_text = detail.get("type", {}).get("text", "").lower()
        type_id   = detail.get("type", {}).get("id", "").lower()
        is_goal   = ("goal" in type_text or type_id in ["score", "goal"]) and "own" not in type_text
        if not is_goal:
            continue
        athletes = detail.get("athletesInvolved", [])
        if not athletes:
            continue
        name = athletes[0].get("displayName", "")
        team_id = str(detail.get("team", {}).get("id", ""))
        country = team_country.get(team_id, "")
        if name:
            goals.append((name, country))

    return goals

def fetch_all_scorers(completed_event_ids):
    """Fetch goal scorer data from ESPN summaries for all completed matches."""
    goal_counts = {}   # player_name -> {goals, country}
    fetched = 0

    for event_id in completed_event_ids:
        if not event_id:
            continue
        try:
            data = fetch_summary(event_id)

            # Build team_id -> country map from this summary
            team_country = {}
            header_comps = data.get("header", {}).get("competitions", [{}])
            if header_comps:
                for c in header_comps[0].get("competitors", []):
                    tid  = str(c.get("team", {}).get("id", ""))
                    cname = norm(c.get("team", {}).get("displayName", ""))
                    if tid and cname:
                        team_country[tid] = cname

            goals = parse_scorers_from_summary(data, team_country)
            for (name, country) in goals:
                if name not in goal_counts:
                    goal_counts[name] = {"goals": 0, "country": country}
                goal_counts[name]["goals"] += 1
                if not goal_counts[name]["country"] and country:
                    goal_counts[name]["country"] = country

            fetched += 1
            time.sleep(0.2)   # Be polite to ESPN's servers

        except Exception as e:
            print(f"  Summary {event_id} failed: {e}")
            continue

    print(f"  Processed {fetched}/{len(completed_event_ids)} match summaries")

    sorted_scorers = sorted(
        [{"name": n, "goals": v["goals"], "country": v["country"]}
         for n, v in goal_counts.items() if v["goals"] > 0],
        key=lambda x: -x["goals"]
    )
    return sorted_scorers

def inject_scorers(scorers, html):
    """Replace TOP_SCORERS_DATA placeholder in HTML with live data."""
    if not scorers:
        return html, False
    pattern = r'const TOP_SCORERS_DATA = \[.*?\];'
    replacement = 'const TOP_SCORERS_DATA = ' + json.dumps(scorers, ensure_ascii=False) + ';'
    new_html = re.sub(pattern, replacement, html, flags=re.DOTALL)
    changed = new_html != html
    if changed:
        print(f"  Injected {len(scorers)} scorers into HTML")
    return new_html, changed

# ── RESULT HELPERS ─────────────────────────────────────────────────────────────

def make_result_str(ta, tb, sa, sb):
    if sa > sb:   return f"{ta} {sa}\u2013{sb}"
    elif sb > sa: return f"{tb} {sb}\u2013{sa}"
    else:         return f"{sa}\u2013{sb} Draw"

def make_result(t1, t2, s1, s2):
    if s1 > s2:   return f"{t1} {s1}\u2013{s2}"
    elif s2 > s1: return f"{t2} {s2}\u2013{s1}"
    else:         return f"{s1}\u2013{s2} Draw"

# ── HTML UPDATE FUNCTIONS ──────────────────────────────────────────────────────

def update_group_html(group_results, html):
    updated = already = 0
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
            cur = re.search(
                r'\["group","[^"]*","' + re.escape(t1) + r'","' + re.escape(t2) + r'",'
                r'"[^"]*","[^"]*","[^"]*","([^"]*)"', html)
            if cur and cur.group(1) == result:
                already += 1; matched = True; break
    print(f"  Group: {updated} updated, {already} already correct")
    return html, updated

def update_knockout_html(ko_updates, html):
    updated = already = 0
    for (ist_iso, ta, tb, result) in ko_updates:
        existing = re.search(
            r'\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'",'
            r'"' + re.escape(ist_iso) + r'","[^"]*","[^"]*","([^"]*)"', html)
        if existing:
            if result and existing.group(1) != result:
                pat = (r'(\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'",'
                       r'"' + re.escape(ist_iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])')
                new_html = re.sub(pat, r'\g<1>"' + result + r'"\2', html)
                if new_html != html:
                    html = new_html; updated += 1
            else:
                already += 1
            continue
        if re.search(r'\["(?:ko|final)","[^"]*","' + re.escape(tb) + r'","' + re.escape(ta) + r'",'
                     r'"' + re.escape(ist_iso) + r'"', html):
            already += 1; continue
        iso_pat = (r'(\["(?:ko|final)","[^"]*",)"[^"]*","[^"]*"'
                   r'(,"' + re.escape(ist_iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])')
        repl = r'\g<1>"' + ta + '","' + tb + r'"\g<2>"' + (result or "") + r'"\3'
        new_html = re.sub(iso_pat, repl, html)
        if new_html != html:
            html = new_html; updated += 1
            print(f"  KO: {ta} vs {tb} at {ist_iso}" + (f" → {result}" if result else " (upcoming)"))
    print(f"  Knockout: {updated} updated, {already} already correct")
    return html, updated

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    try:
        data = fetch_scoreboard()
        group_results, ko_updates, completed_ids = parse_events(data)
        print(f"Parsed: {len(group_results)} group results, {len(completed_ids)} completed matches for scorer data")
    except Exception as e:
        print(f"ESPN scoreboard fetch failed: {e}")
        sys.exit(0)

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    original = html
    total = 0

    # Update match results
    html, n = update_group_html(group_results, html)
    total += n
    html, n = update_knockout_html(ko_updates, html)
    total += n

    # Fetch and inject individual scorer data
    print(f"\nFetching scorer data for {len(completed_ids)} matches...")
    scorers = fetch_all_scorers(completed_ids)
    print(f"  Found {len(scorers)} players who have scored")
    html, changed = inject_scorers(scorers, html)
    if changed:
        total += 1

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nDone — {total} updates written to index.html")
    else:
        print(f"\nNo changes — everything already current")

if __name__ == "__main__":
    main()
