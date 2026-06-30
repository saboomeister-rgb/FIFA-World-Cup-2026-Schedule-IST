import requests
import re
import sys
import json
import time
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

NAME_MAP = {
    "United States": "USA", "Turkey": "Türkiye",
    "Bosnia and Herzegovina": "Bosnia & Herz.", "Bosnia-Herzegovina": "Bosnia & Herz.",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Côte d'Ivoire": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo", "Congo, DR": "DR Congo", "Democratic Republic of Congo": "DR Congo",
    "Korea Republic": "South Korea", "Czech Republic": "Czechia",
}
def norm(name): return NAME_MAP.get(name, name)

def to_ist_iso(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(IST).strftime('%Y-%m-%dT%H:%M')
    except Exception:
        return None

def fetch_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=20260611-20260720&limit=150"
    r = requests.get(url, timeout=20); r.raise_for_status(); return r.json()

def fetch_summary(eid):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={eid}"
    r = requests.get(url, timeout=15); r.raise_for_status(); return r.json()

def make_result_str(ta, tb, sa, sb):
    if sa > sb: return f"{ta} {sa}\u2013{sb}"
    elif sb > sa: return f"{tb} {sb}\u2013{sa}"
    else: return f"{sa}\u2013{sb} Draw"

def make_result(t1, t2, s1, s2):
    if s1 > s2: return f"{t1} {s1}\u2013{s2}"
    elif s2 > s1: return f"{t2} {s2}\u2013{s1}"
    else: return f"{s1}\u2013{s2} Draw"

def parse_events(data):
    events = data.get("events", [])
    print(f"ESPN scoreboard: {len(events)} events")
    group_results, ko_updates, completed_ids = [], [], []
    for event in events:
        comps = event.get("competitions", [])
        if not comps: continue
        comp = comps[0]
        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        cs = comp.get("competitors", [])
        if len(cs) < 2: continue
        home = next((c for c in cs if c.get("homeAway")=="home"), cs[0])
        away = next((c for c in cs if c.get("homeAway")=="away"), cs[1])
        ta = norm(home.get("team", {}).get("displayName", ""))
        tb = norm(away.get("team", {}).get("displayName", ""))
        iso = to_ist_iso(event.get("date", ""))
        if not iso: continue
        if completed and ta and tb and 'TBD' not in ta and 'TBD' not in tb:
            try:
                sa, sb = int(home.get("score", -1)), int(away.get("score", -1))
            except (ValueError, TypeError):
                sa = sb = -1
            if sa >= 0 and sb >= 0:
                # Detect penalty shootout — ESPN provides shootoutScore when scores level
                pa = home.get("shootoutScore")
                pb = away.get("shootoutScore")
                has_pens = pa is not None and pb is not None and (sa == sb)
                result = make_result_pen(ta, tb, sa, sb, pa, pb, has_pens)
                group_results.append((ta, tb, sa, sb, pa, pb, has_pens))
                ko_updates.append((iso, ta, tb, result))
                completed_ids.append(event.get("id"))
        elif not completed and ta and tb and 'TBD' not in ta and 'TBD' not in tb:
            ko_updates.append((iso, ta, tb, ""))
    return group_results, ko_updates, completed_ids

def make_result_pen(ta, tb, sa, sb, pa, pb, has_pens):
    """Result string. For penalties: 'Morocco 1–1 (4–2 pens)'."""
    if has_pens:
        try:
            pa, pb = int(pa), int(pb)
        except (ValueError, TypeError):
            has_pens = False
    if has_pens:
        winner = ta if pa > pb else tb
        wp, lp = (pa, pb) if pa > pb else (pb, pa)
        return f"{winner} {sa}\u2013{sb} ({wp}\u2013{lp} pens)"
    # Normal result
    if sa > sb:   return f"{ta} {sa}\u2013{sb}"
    elif sb > sa: return f"{tb} {sb}\u2013{sa}"
    else:         return f"{sa}\u2013{sb} Draw"

# ── SCORER PARSING (robust, multi-field) ───────────────────────────────────────

def extract_goals_from_summary(data):
    """
    Returns list of (player_name, country_name).
    Tries keyEvents first (most reliable for soccer), then scoringPlays, then details.
    """
    goals = []

    # Build team id/abbr -> country name map from boxscore + header
    team_map = {}
    for c in data.get("boxscore", {}).get("teams", []):
        t = c.get("team", {})
        tid = str(t.get("id", ""))
        nm = norm(t.get("displayName", ""))
        if tid and nm: team_map[tid] = nm
    for hc in data.get("header", {}).get("competitions", [{}]):
        for c in hc.get("competitors", []):
            t = c.get("team", {})
            tid = str(t.get("id", ""))
            nm = norm(t.get("displayName", ""))
            if tid and nm: team_map[tid] = nm

    def country_for(team_obj):
        if not team_obj: return ""
        tid = str(team_obj.get("id", ""))
        return team_map.get(tid, norm(team_obj.get("displayName", "")))

    def is_goal_type(txt, tid=""):
        t = (txt or "").lower()
        if "own goal" in t: return True   # count for completeness; rare
        return ("goal" in t) or (str(tid) in ("70","98"))  # 70/98 are goal type ids seen in ESPN soccer

    # ── Source 1: keyEvents ──
    for ev in data.get("keyEvents", []):
        txt = ev.get("type", {}).get("text", "")
        tid = ev.get("type", {}).get("id", "")
        # ESPN soccer often flags goals via a 'scoringPlay' boolean
        if ev.get("scoringPlay") or is_goal_type(txt, tid):
            ath = ev.get("athletesInvolved") or ev.get("participants") or []
            if ath:
                nm = ath[0].get("displayName") or ath[0].get("athlete", {}).get("displayName", "")
                if nm:
                    goals.append((nm, country_for(ev.get("team", {}))))

    if goals: return goals

    # ── Source 2: scoringPlays ──
    for play in data.get("scoringPlays", []):
        ath = play.get("athletesInvolved", [])
        if ath:
            nm = ath[0].get("displayName", "")
            if nm:
                goals.append((nm, country_for(play.get("team", {}))))

    if goals: return goals

    # ── Source 3: competitions[].details ──
    comps = data.get("header", {}).get("competitions", [])
    details = comps[0].get("details", []) if comps else []
    for d in details:
        txt = d.get("type", {}).get("text", "")
        tid = d.get("type", {}).get("id", "")
        if d.get("scoringPlay") or is_goal_type(txt, tid):
            ath = d.get("athletesInvolved", [])
            if ath:
                nm = ath[0].get("displayName", "")
                if nm:
                    goals.append((nm, country_for(d.get("team", {}))))

    return goals

def fetch_all_scorers(ids):
    counts = {}
    ok = 0
    for eid in ids:
        if not eid: continue
        try:
            data = fetch_summary(eid)
            goals = extract_goals_from_summary(data)
            for (nm, country) in goals:
                if nm not in counts:
                    counts[nm] = {"goals": 0, "country": country}
                counts[nm]["goals"] += 1
                if not counts[nm]["country"] and country:
                    counts[nm]["country"] = country
            ok += 1
            time.sleep(0.15)
        except Exception as e:
            print(f"  summary {eid} failed: {e}")
    print(f"  Summaries processed: {ok}/{len(ids)}")
    scorers = sorted(
        [{"name": n, "goals": v["goals"], "country": v["country"]} for n, v in counts.items() if v["goals"] > 0],
        key=lambda x: -x["goals"]
    )
    # Log top 10 for visibility in workflow output
    for p in scorers[:10]:
        print(f"    {p['goals']}  {p['name']} ({p['country']})")
    return scorers

def inject_scorers(scorers, html):
    if not scorers: return html, False
    pat = r'const TOP_SCORERS_DATA = \[.*?\];'
    rep = 'const TOP_SCORERS_DATA = ' + json.dumps(scorers, ensure_ascii=False) + ';'
    new = re.sub(pat, rep, html, flags=re.DOTALL)
    return new, (new != html)

def update_group_html(results, html):
    upd = alr = 0
    for row in results:
        ta, tb, sa, sb = row[0], row[1], row[2], row[3]
        # Group matches never go to penalties, so use simple result here
        for (t1, t2, s1, s2) in [(ta, tb, sa, sb), (tb, ta, sb, sa)]:
            result = make_result(t1, t2, s1, s2)
            pat = (r'(\["group","[^"]*","' + re.escape(t1) + r'","' + re.escape(t2) + r'","[^"]*","[^"]*","[^"]*",)"[^"]*"(\])')
            new = re.sub(pat, r'\g<1>"' + result + r'"\2', html)
            if new != html: html = new; upd += 1; break
            cur = re.search(r'\["group","[^"]*","' + re.escape(t1) + r'","' + re.escape(t2) + r'","[^"]*","[^"]*","[^"]*","([^"]*)"', html)
            if cur and cur.group(1) == result: alr += 1; break
    print(f"  Group: {upd} updated, {alr} already correct")
    return html, upd

def update_knockout_html(updates, html):
    upd = alr = 0
    for (iso, ta, tb, result) in updates:
        ex = re.search(r'\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'","' + re.escape(iso) + r'","[^"]*","[^"]*","([^"]*)"', html)
        if ex:
            if result and ex.group(1) != result:
                pat = (r'(\["(?:ko|final)","[^"]*","' + re.escape(ta) + r'","' + re.escape(tb) + r'","' + re.escape(iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])')
                new = re.sub(pat, r'\g<1>"' + result + r'"\2', html)
                if new != html: html = new; upd += 1
            else: alr += 1
            continue
        if re.search(r'\["(?:ko|final)","[^"]*","' + re.escape(tb) + r'","' + re.escape(ta) + r'","' + re.escape(iso) + r'"', html):
            alr += 1; continue
        iso_pat = (r'(\["(?:ko|final)","[^"]*",)"[^"]*","[^"]*"(,"' + re.escape(iso) + r'","[^"]*","[^"]*",)"[^"]*"(\])')
        repl = r'\g<1>"' + ta + '","' + tb + r'"\g<2>"' + (result or "") + r'"\3'
        new = re.sub(iso_pat, repl, html)
        if new != html:
            html = new; upd += 1
            print(f"  KO: {ta} vs {tb} at {iso}" + (f" -> {result}" if result else " (upcoming)"))
    print(f"  Knockout: {upd} updated, {alr} already correct")
    return html, upd

def main():
    try:
        data = fetch_scoreboard()
        results, ko_updates, completed_ids = parse_events(data)
        print(f"Parsed: {len(results)} group results, {len(completed_ids)} completed matches")
    except Exception as e:
        print(f"Scoreboard fetch failed: {e}"); sys.exit(0)

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    original = html
    total = 0

    html, n = update_group_html(results, html); total += n
    html, n = update_knockout_html(ko_updates, html); total += n

    print(f"\nFetching scorers from {len(completed_ids)} match summaries...")
    scorers = fetch_all_scorers(completed_ids)
    print(f"  Total scorers found: {len(scorers)}")
    html, changed = inject_scorers(scorers, html)
    if changed:
        total += 1
        print("  TOP_SCORERS_DATA injected into HTML")
    else:
        print("  No scorer data to inject (list empty)")

    if html != original:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nDone — {total} updates written")
    else:
        print("\nNo changes")

if __name__ == "__main__":
    main()
