#!/usr/bin/env python3
"""
Writes data/live.json for one team: the sprint that is open right now (or the last
one that closed), plus the month in progress. Nothing else in the site depends on it,
so closed months and quarters stay exactly as they were published.

Environment:
  JIRA_BASE    e.g. https://wellfit.atlassian.net
  JIRA_EMAIL   the Atlassian account the API token belongs to
  JIRA_TOKEN   an Atlassian API token  (id.atlassian.com -> Security -> API tokens)

Usage:
  python3 scripts/fetch_jira.py --team EDW --board 11 --project EDW --out data/live.json
  python3 scripts/fetch_jira.py --team DS  --board 257 --project "Database Services" --out data/live.json
"""
import os, sys, json, base64, argparse, datetime as dt
from urllib import request, parse, error

BASE  = os.environ.get("JIRA_BASE", "https://wellfit.atlassian.net").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("JIRA_TOKEN", "")
SP_FIELD = os.environ.get("JIRA_SP_FIELD", "customfield_10033")   # Story Points

if not (EMAIL and TOKEN):
    sys.exit("JIRA_EMAIL and JIRA_TOKEN must be set")

AUTH = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
HDRS = {"Authorization": f"Basic {AUTH}", "Accept": "application/json",
        "Content-Type": "application/json"}

def call(path, method="GET", body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(url, data=data, headers=HDRS, method=method)
    try:
        with request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except error.HTTPError as e:
        sys.exit(f"Jira {e.code} on {method} {path}: {e.read()[:300].decode(errors='replace')}")

def search(jql, fields, expand=None, cap=6):
    """POST /search/jql, following nextPageToken."""
    out, token, guard = [], None, 0
    while guard < cap:
        body = {"jql": jql, "maxResults": 100, "fields": fields}
        if expand: body["expand"] = expand
        if token:  body["nextPageToken"] = token
        j = call("/rest/api/3/search/jql", "POST", body)
        out += j.get("issues", [])
        token = j.get("nextPageToken")
        guard += 1
        if not token: break
    return out

def sprints(board):
    out, start = [], 0
    while True:
        j = call(f"/rest/agile/1.0/board/{board}/sprint?startAt={start}&maxResults=50")
        out += j.get("values", [])
        if j.get("isLast", True): break
        start += 50
    return out

def sp_of(issue):
    v = issue["fields"].get(SP_FIELD)
    try: return float(v) if v is not None else 0.0
    except (TypeError, ValueError): return 0.0

def sprint_detail(board, sp, project):
    """Day-1 commitment from the Sprint-field changelog; completion from status history."""
    sid, name = sp["id"], sp["name"]
    issues = search(f'project = "{project}" AND sprint = {sid}',
                    ["status", "summary", SP_FIELD, "resolutiondate", "labels", "issuetype"],
                    expand="changelog")
    start = dt.datetime.fromisoformat(sp["startDate"].replace("Z", "+00:00"))
    end_s = sp.get("completeDate") or sp.get("endDate")
    end   = dt.datetime.fromisoformat(end_s.replace("Z", "+00:00"))
    day1  = start + dt.timedelta(days=1)
    now   = dt.datetime.now(dt.timezone.utc)
    horizon = min(end, now)
    DONE = {"Closed", "Done", "Resolved"}

    def entered(i):
        t = None
        for h in i.get("changelog", {}).get("histories", []):
            for it in h["items"]:
                if it["field"] != "Sprint": continue
                to   = [x.strip() for x in (it.get("toString")   or "").split(",")]
                frm  = [x.strip() for x in (it.get("fromString") or "").split(",")]
                if name in to and name not in frm:
                    d = dt.datetime.fromisoformat(h["created"].replace("Z", "+00:00"))
                    if t is None or d < t: t = d
        return t

    def done_at(i):
        t = None
        for h in i.get("changelog", {}).get("histories", []):
            for it in h["items"]:
                if it["field"] == "status" and it.get("toString") in DONE:
                    d = dt.datetime.fromisoformat(h["created"].replace("Z", "+00:00"))
                    if t is None or d < t: t = d
        return t

    rows, committed, final, completed, items_done = [], 0.0, 0.0, 0.0, 0
    for i in issues:
        v, e, d = sp_of(i), entered(i), done_at(i)
        in_d1 = (e is None) or (e <= day1)
        final += v
        if in_d1: committed += v
        if d is not None and d <= horizon:
            completed += v; items_done += 1
        rows.append((e or start, v, d))

    days = max(1, int((horizon - start).total_seconds() // 86400) + 1)
    burn, scope = [], []
    for k in range(days + 1):
        t = start + dt.timedelta(days=k)
        s = sum(v for e, v, _ in rows if e <= t)
        r = sum(v for e, v, d in rows if e <= t and not (d and d <= t))
        scope.append(round(s, 1)); burn.append(round(r, 1))

    dist = {}
    for i in issues:
        st = i["fields"]["status"]["name"]
        dist[st] = dist.get(st, 0) + 1

    # Jira's own sprint report: what was removed / left open
    spill = {"open_items": 0, "open_pts": 0, "out_items": 0, "out_pts": 0, "done_pts": 0}
    try:
        rep = call(f"/rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId={board}&sprintId={sid}")
        c = rep.get("contents", {})
        val = lambda o: (o or {}).get("value") or 0
        spill = {"open_items": len(c.get("issuesNotCompletedInCurrentSprint", [])),
                 "open_pts":  val(c.get("issuesNotCompletedEstimateSum")),
                 "out_items": len(c.get("puntedIssues", [])),
                 "out_pts":   val(c.get("puntedIssuesEstimateSum")),
                 "done_pts":  val(c.get("completedIssuesEstimateSum"))}
    except SystemExit:
        pass   # closed-sprint report can be unavailable; the rest of the panel still works

    gone = spill["open_pts"] + spill["out_pts"]
    allp = spill["done_pts"] + gone
    elapsed = (now - start).total_seconds() / max(1, (end - start).total_seconds())

    return {
        "name": name, "state": sp["state"],
        "start": sp["startDate"][:10], "end": (end_s or "")[:10],
        "goal": (sp.get("goal") or "").strip(),
        "items": len(issues), "items_done": items_done,
        "committed": round(committed), "final": round(final), "completed": round(completed),
        "scope_change": round(100*(final-committed)/committed) if committed else None,
        "vs_commitment": round(100*completed/committed) if committed else None,
        "time_elapsed": min(100, round(100*elapsed)),
        "spill": spill, "spill_rate": round(100*gone/allp) if allp else None,
        "dist": dist, "burn": burn, "scope": scope,
    }

def month_so_far(project):
    today = dt.date.today()
    first = today.replace(day=1)
    nxt   = (first + dt.timedelta(days=32)).replace(day=1)
    base  = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
             f'AND resolution = Done AND resolved >= "{first}" AND resolved < "{nxt}"')
    iss   = search(base, ["resolutiondate", SP_FIELD, "labels", "issuetype", "assignee"])
    unp   = sum(1 for i in iss
                if any(l.lower() in ("unplanned", "not planned", "not_planned")
                       for l in i["fields"].get("labels", []))
                or i["fields"]["issuetype"]["name"] == "Urgent Task")
    dar   = sum(1 for i in iss if any("access" in l.lower() for l in i["fields"].get("labels", [])))
    pts   = sum(sp_of(i) for i in iss)
    people = {}
    for i in iss:
        a = (i["fields"].get("assignee") or {}).get("displayName")
        if a: people[a] = people.get(a, 0) + 1
    return {"month": first.strftime("%Y-%m"), "label": first.strftime("%B %Y"),
            "day": today.day, "closed": len(iss), "points": round(pts),
            "unplanned": unp, "unplanned_pct": round(100*unp/len(iss), 1) if iss else None,
            "access_requests": dar,
            "people_active": sum(1 for _, c in people.items() if c >= 2)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True)
    ap.add_argument("--board", type=int, required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="data/live.json")
    a = ap.parse_args()

    all_sp = [s for s in sprints(a.board) if s.get("startDate")]
    mine   = [s for s in all_sp if s["name"].upper().startswith(a.team.upper())]
    active = [s for s in mine if s["state"] == "active"]
    future = sorted([s for s in mine if s["state"] == "future"], key=lambda s: s["startDate"])
    closed = sorted([s for s in mine if s["state"] == "closed"],
                    key=lambda s: s.get("completeDate") or s["startDate"])

    if active:
        sp, kind = active[0], "active"
    elif closed:
        sp, kind = closed[-1], "recent"
    else:
        sp, kind = None, "none"

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "team": a.team, "board": a.board, "kind": kind,
        "sprint": sprint_detail(a.board, sp, a.project) if sp else None,
        "next": ({"name": future[0]["name"], "start": future[0]["startDate"][:10],
                  "state": "not started"} if future else None),
        "month": month_so_far(a.project),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{a.out}: {kind} {out['sprint']['name'] if out['sprint'] else '—'} · "
          f"month {out['month']['closed']} closed")

if __name__ == "__main__":
    main()
