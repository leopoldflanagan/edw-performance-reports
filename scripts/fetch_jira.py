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

BASE  = (os.environ.get("JIRA_BASE") or "https://wellfit.atlassian.net").strip().rstrip("/")
EMAIL = (os.environ.get("JIRA_EMAIL") or "").strip()
TOKEN = (os.environ.get("JIRA_TOKEN") or "").strip()
SP_FIELD = os.environ.get("JIRA_SP_FIELD", "customfield_10033")   # Story Points

def _mask(e):
    if not e:          return "EMPTY"
    u, at, d = e.partition("@")
    if not at:         return "no @ in the value"
    return f"{u[:2]}***@{d}"

print("--- config check -------------------------------------------", flush=True)
print(f"  JIRA_BASE   {BASE or 'EMPTY'}", flush=True)
print(f"  JIRA_EMAIL  {_mask(EMAIL)}", flush=True)
print(f"  JIRA_TOKEN  {'set, ' + str(len(TOKEN)) + ' characters' if TOKEN else 'EMPTY'}", flush=True)
print("------------------------------------------------------------", flush=True)

_bad = [n for n, v in (("JIRA_EMAIL", EMAIL), ("JIRA_TOKEN", TOKEN)) if not v]
if _bad:
    sys.exit(
        "CONFIG ERROR: " + " and ".join(_bad) + " arrived empty.\n"
        "  Settings -> Secrets and variables -> Actions -> tab 'Secrets'.\n"
        "  The name must match exactly, uppercase, no spaces. A value created in the\n"
        "  'Variables' tab instead of 'Secrets' reaches the job as an empty string."
    )

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
        hint = {
            401: "401 = Jira rejected the e-mail/token pair. Most often the e-mail is not the "
                 "Atlassian account the token was created under, or the token was pasted with a "
                 "stray space or line break.",
            403: "403 = the credentials are valid but that account cannot see this board/project.",
            404: "404 = that board or project id does not exist on this site.",
        }.get(e.code, "")
        sys.exit(f"Jira {e.code} on {method} {path}\n  {hint}\n  body: "
                 f"{e.read()[:300].decode(errors='replace')}")

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


def _entered_sprint(i, name):
    """When this issue first joined that sprint, per the Sprint-field changelog."""
    t = None
    for h in i.get("changelog", {}).get("histories", []):
        for it in h["items"]:
            if it["field"] != "Sprint": continue
            to  = [x.strip() for x in (it.get("toString")   or "").split(",")]
            frm = [x.strip() for x in (it.get("fromString") or "").split(",")]
            if name in to and name not in frm:
                d = dt.datetime.fromisoformat(h["created"].replace("Z", "+00:00"))
                if t is None or d < t: t = d
    return t

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

    entered = lambda i: _entered_sprint(i, name)

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
    punted = []
    try:
        rep = call(f"/rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId={board}&sprintId={sid}")
        c = rep.get("contents", {})
        val = lambda o: (o or {}).get("value") or 0
        spill = {"open_items": len(c.get("issuesNotCompletedInCurrentSprint", [])),
                 "open_pts":  val(c.get("issuesNotCompletedEstimateSum")),
                 "out_items": len(c.get("puntedIssues", [])),
                 "out_pts":   val(c.get("puntedIssuesEstimateSum")),
                 "done_pts":  val(c.get("completedIssuesEstimateSum"))}
        punted = [x.get("key") for x in c.get("puntedIssues", []) if x.get("key")]
    except SystemExit:
        pass   # closed-sprint report can be unavailable; the rest of the panel still works

    # Issues removed from the sprint before it closed are gone from `sprint = N`, and
    # they are exactly the ones that were stuck. Pull them back for the flow measures.
    issues_all = list(issues)
    if punted:
        have = {i["key"] for i in issues}
        extra = search(f'key in ({", ".join(punted)})',
                       ["status", "summary", SP_FIELD, "resolutiondate", "labels", "issuetype"],
                       expand="changelog")
        issues_all += [i for i in extra if i["key"] not in have]

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
        "_issues": issues, "_issues_all": issues_all,
        "_start": start, "_end": end, "_day1": day1,
    }

def _clean(d):
    """Strip the raw payload the month block needs but the panel must not carry."""
    return {k: v for k, v in d.items() if not k.startswith("_")}

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


def cyc_status(c):
    return "healthy" if (c["med"] <= 6 and c["avg"] <= 9) else (
           "warning" if (c["med"] <= 7.2 and c["avg"] <= 10.8) else "risk")
# ---------------------------------------------------------------- month block
# Everything below builds the SAME shape the frozen periods use, so a month that
# closes can be appended to data/frozen.json and never recomputed again.

REACTIVE_LABELS = {"unplanned", "not planned", "not_planned", "urgent"}
TERMINAL     = {"Closed", "Done", "Resolved", "Won't Do", "Cancelled", "Duplicate"}
QUEUE_OUT    = {"Backlog"}   # waiting to be pulled is not a workflow bottleneck
STALLED_DAYS = 3             # days in the current, non-terminal status at sprint end

def _dtp(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def _median(xs):
    if not xs: return 0.0
    v = sorted(xs); n = len(v)
    return v[n//2] if n % 2 else (v[n//2 - 1] + v[n//2]) / 2

def _is_reactive(i):
    f = i["fields"]
    if f.get("issuetype", {}).get("name") == "Urgent Task": return True
    return any((l or "").lower() in REACTIVE_LABELS for l in f.get("labels", []))

def split_of(issues, sprint_name, day1, start):
    """Of what came in after day 1: how much carried a reactive marker."""
    react = plan = 0
    for i in issues:
        e = _entered_sprint(i, sprint_name)
        if e is None or e <= day1:      # already there on day 1, not an addition
            continue
        if _is_reactive(i): react += 1
        else:                plan  += 1
    if react + plan == 0:
        return None                      # no additions — the page shows "no data", not zero
    return {"react": react, "plan": plan, "pct": round(100*react/(react+plan))}

def tis_of(issues, start, end, sprint_name=None):
    """Median days an item sat in each status.

    Two decisions worth knowing about, because they change the answer a lot:

    * the clock starts when the item JOINED the sprint, not when the sprint started,
      so something pulled in on day 9 is not charged for the first nine days;
    * the population must include the issues that were REMOVED at close (see
      sprint_detail). EDW empties its sprints before closing them, so measuring only
      what stayed makes every closed sprint look clean: for Sprint 21-26 the same
      calculation reads 36 items and 2 stalled without them, and 52 items and 11
      stalled with them.
    """
    per, dist, stalled = {}, {}, 0
    for i in issues:
        st_now = i["fields"]["status"]["name"]
        dist[st_now] = dist.get(st_now, 0) + 1
        joined = _entered_sprint(i, sprint_name) if sprint_name else None
        frm = joined if (joined and joined > start) else start
        moves = []
        for h in i.get("changelog", {}).get("histories", []):
            for it in h["items"]:
                if it["field"] == "status":
                    moves.append((_dtp(h["created"]), it.get("fromString"), it.get("toString")))
        moves.sort()
        cur, since = (moves[0][1] if moves else st_now), frm
        for when, _f, to in moves:
            if when < frm:
                cur = to; continue
            if when > end:
                break
            per.setdefault(cur, []).append(max(0.0, (when - since).total_seconds()/86400))
            cur, since = to, when
        tail = max(0.0, (end - since).total_seconds()/86400)
        per.setdefault(cur, []).append(tail)
        if cur not in TERMINAL and tail > STALLED_DAYS:
            stalled += 1
    tis = {k: {"n": len(v), "med": round(_median(v), 2)} for k, v in per.items() if v}
    cand = {k: d for k, d in tis.items() if k not in TERMINAL and k not in QUEUE_OUT}
    worst_st = max(cand, key=lambda k: cand[k]["med"]) if cand else None
    return {"tis": tis, "dist": dist, "stalled": stalled,
            "worst": cand[worst_st]["med"] if worst_st else 0,
            "worstSt": worst_st, "items": len(issues)}

def cycle_of(project, first, nxt):
    """First entry into In Development -> resolution. Calendar days, closed items only."""
    jql = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
           f'AND resolution = Done AND resolved >= "{first}" AND resolved < "{nxt}"')
    iss = search(jql, ["resolutiondate", "status"], expand="changelog", cap=8)
    days, nodev = [], 0
    for i in iss:
        rd = i["fields"].get("resolutiondate")
        if not rd: continue
        first_dev = None
        for h in i.get("changelog", {}).get("histories", []):
            for it in h["items"]:
                if it["field"] == "status" and it.get("toString") == "In Development":
                    d = _dtp(h["created"])
                    if first_dev is None or d < first_dev: first_dev = d
        if first_dev is None:
            nodev += 1; continue
        days.append((_dtp(rd) - first_dev).total_seconds()/86400)
    if not days:
        return {"med": 0, "avg": 0, "n": 0, "mx": 0, "nodev": nodev, "base": len(iss)}
    return {"med": round(_median(days), 2), "avg": round(sum(days)/len(days), 2),
            "n": len(days), "mx": round(max(days), 2), "nodev": nodev, "base": len(iss)}

def cap_of(project, first, nxt):
    """items closed, items carrying points, points, people with >= 2 closed items."""
    jql = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
           f'AND resolution = Done AND resolved >= "{first}" AND resolved < "{nxt}"')
    iss = search(jql, [SP_FIELD, "assignee"], cap=8)
    people = {}
    for i in iss:
        a = (i["fields"].get("assignee") or {}).get("displayName")
        if a: people[a] = people.get(a, 0) + 1
    return [len(iss),
            sum(1 for i in iss if sp_of(i) > 0),
            round(sum(sp_of(i) for i in iss)),
            sum(1 for _, c in people.items() if c >= 2)]


# ---------------------------------------------------------------- the month block
MONTH_NAMES = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]

def _mday(d):      # "Apr 27"
    return f"{MONTH_NAMES[d.month-1][:3]} {d.day}"

def sprints_of_month(mine, ym):
    """A sprint belongs to the month it ENDS in — the same rule the closed months use."""
    out = []
    for s in mine:
        e = s.get("completeDate") or s.get("endDate")
        if e and e[:7] == ym and s["state"] != "future":
            out.append(s)
    return sorted(out, key=lambda s: s.get("completeDate") or s["endDate"])

def verdict(closed, cyc, unp_pct, prev_closed, day=None, days=None):
    """The health call and its one-line headline, from rules rather than from a person.
    A month still running is judged at pace: comparing 29 items on day 15 against a
    full month would call every open month a collapse."""
    notes, status = [], "healthy"
    rank = ["healthy", "warning", "risk"]
    up = lambda a, b: max(a, b, key=rank.index)
    share = (day / days) if (day and days) else 1.0
    open_month = share < 1.0

    if unp_pct is None:
        notes.append("the Unplanned label was not applied, so reactive work cannot be measured")
        status = up(status, "warning")
    elif unp_pct >= 15:
        notes.append(f"unplanned work at {unp_pct}% of everything closed")
        status = up(status, "risk")
    elif unp_pct >= 10:
        notes.append(f"unplanned work at {unp_pct}%")
        status = up(status, "warning")

    cs = cyc_status(cyc)
    if cs == "risk":
        notes.append(f"cycle time median {cyc['med']:.1f}d and average {cyc['avg']:.1f}d, both past the healthy band")
        status = up(status, "risk")
    elif cs == "warning":
        notes.append(f"cycle time average {cyc['avg']:.1f}d against a {cyc['med']:.1f}d median - a long tail")
        status = up(status, "warning")

    if prev_closed:
        ref = prev_closed * share
        gap = 100 * (closed - ref) / ref if ref else 0
        if gap <= -25:
            notes.insert(0, f"running {abs(gap):.0f}% behind last month's pace")
            status = up(status, "warning")

    if open_month:
        pace = closed / share
        move = (f"{closed} items closed in the first {day} days, a pace of about {pace:.0f} "
                f"for the month against {prev_closed} last month" if prev_closed
                else f"{closed} items closed in the first {day} days")
    else:
        move = (f"{closed} items closed against {prev_closed} the month before"
                if prev_closed else f"{closed} items closed")

    headline = move + ((". " + notes[0][0].upper() + notes[0][1:] + ".") if notes else ".")
    return status, headline, notes

def month_block(board, project, team, mine, ym, prev_closed=None):
    y, m = ym.split("-")
    first = dt.date(int(y), int(m), 1)
    nxt   = (first + dt.timedelta(days=32)).replace(day=1)
    label = f"{MONTH_NAMES[int(m)-1]} {y}"

    rows, spill, split, tis, names = {}, {}, {}, {}, []
    for s in sprints_of_month(mine, ym):
        d = sprint_detail(board, s, project)
        n = d["name"]; names.append(n)
        st, en = _dtp(s["startDate"]), _dtp(s.get("completeDate") or s["endDate"])
        rows[n] = [n, _mday(st), _mday(en), d["items"], d["items_done"],
                   d["committed"], d["final"], d["completed"],
                   d["scope_change"] if d["scope_change"] is not None else 0,
                   d["burn"], d["scope"]]
        sp_ = d["spill"]
        spill[n] = {"done": [d["items_done"], round(sp_["done_pts"])],
                    "open": [sp_["open_items"], round(sp_["open_pts"])],
                    "out":  [sp_["out_items"],  round(sp_["out_pts"])]}
        split[n] = split_of(d["_issues_all"], n, d["_day1"], d["_start"])
        tis[n]   = tis_of(d["_issues_all"], d["_start"], d["_end"], n)

    cap = cap_of(project, first, nxt)
    cyc = cycle_of(project, first, nxt)

    allres = search(f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
                    f'AND resolved >= "{first}" AND resolved < "{nxt}"',
                    ["resolution", "issuetype", "labels", "summary"], cap=8)
    discarded = sum(1 for i in allres
                    if (i["fields"].get("resolution") or {}).get("name") not in (None, "Done"))
    types, unp_items = {}, []
    for i in allres:
        if (i["fields"].get("resolution") or {}).get("name") != "Done": continue
        t = i["fields"]["issuetype"]["name"]; types[t] = types.get(t, 0) + 1
        if _is_reactive(i): unp_items.append([i["key"], i["fields"].get("summary", "")])
    labelled = any(i["fields"].get("labels") for i in allres)
    unp     = len(unp_items) if labelled else None
    unp_pct = round(100*unp/cap[0], 1) if (unp is not None and cap[0]) else None

    today = dt.date.today()
    days  = (nxt - first).days
    open_month = not (today >= nxt)
    status, headline, notes = verdict(cap[0], cyc, unp_pct, prev_closed,
                                      day=(today.day if open_month else None),
                                      days=(days if open_month else None))

    return {
        "ym": ym,
        "month": {"slug": f"{y}-{m}-{MONTH_NAMES[int(m)-1].lower()}", "label": label,
                  "short": MONTH_NAMES[int(m)-1][:3].upper(),
                  "prev": MONTH_NAMES[int(m)-2] if int(m) > 1 else "December",
                  "prev_closed": prev_closed,
                  "closed": cap[0], "discarded": discarded,
                  "resolved": cap[0] + discarded,
                  "unplanned": unp, "unp_pct": unp_pct,
                  "types": sorted(types.items(), key=lambda kv: -kv[1]),
                  "sprints": names, "unp_items": unp_items,
                  "open": open_month, "day": today.day, "days": days,
                  "status": status, "headline": headline, "notes": notes},
        "SPRINTS": [rows[n] for n in names],
        "SPILL": spill, "SPLIT": split, "TIS": tis,
        "CAP": {m: cap}, "CYC": {m: cyc},
        "complete": all(s["state"] == "closed" for s in sprints_of_month(mine, ym))
                    and dt.date.today() >= nxt,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True)
    ap.add_argument("--board", type=int, required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="data/live.json")
    ap.add_argument("--month-out", default="data/current.json")
    ap.add_argument("--frozen", default="data/frozen.json")
    ap.add_argument("--selfcheck", default="",
                    help="recompute this already-frozen sprint and print the delta")
    a = ap.parse_args()

    all_sp = [s for s in sprints(a.board) if s.get("startDate")]
    mine   = [s for s in all_sp if s["name"].upper().startswith(a.team.upper())]
    active = [s for s in mine if s["state"] == "active"]
    future = sorted([s for s in mine if s["state"] == "future"], key=lambda s: s["startDate"])
    closed = sorted([s for s in mine if s["state"] == "closed"],
                    key=lambda s: s.get("completeDate") or s["startDate"])

    if a.selfcheck:
        return selfcheck(a, mine)

    if active:      sp, kind = active[0], "active"
    elif closed:    sp, kind = closed[-1], "recent"
    else:           sp, kind = None, "none"

    det = sprint_detail(a.board, sp, a.project) if sp else None
    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "team": a.team, "board": a.board, "kind": kind,
        "sprint": _clean(det) if det else None,
        "next": ({"name": future[0]["name"], "start": future[0]["startDate"][:10],
                  "state": "not started"} if future else None),
        "month": month_so_far(a.project),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{a.out}: {kind} {out['sprint']['name'] if out['sprint'] else '-'} - "
          f"month {out['month']['closed']} closed")

    # the month in progress, in the same shape the frozen months use
    ym = dt.date.today().strftime("%Y-%m")
    prev_closed = None
    try:
        fz = json.load(open(a.frozen))
        pm = (dt.date.today().replace(day=1) - dt.timedelta(days=1)).strftime("%m")
        prev_closed = (fz.get("CAP", {}).get(pm) or [None])[0]
    except Exception:
        pass
    blk = month_block(a.board, a.project, a.team, mine, ym, prev_closed)
    with open(a.month_out, "w") as f:
        json.dump(blk, f, indent=1)
    print(f"{a.month_out}: {blk['month']['label']} - {len(blk['SPRINTS'])} sprint(s), "
          f"{blk['month']['closed']} closed, status {blk['month']['status']}, "
          f"month complete: {blk['complete']}")


def selfcheck(a, mine):
    """Recompute a sprint that is already frozen and print every difference.
    A clean run means the automatic pipeline reproduces the hand-curated numbers."""
    fz = json.load(open(a.frozen))
    want = a.selfcheck
    row = next((r for r in fz.get("SPRINTS", []) + fz.get("SPRINTS_Q1", []) if r[0] == want), None)
    if row is None:
        sys.exit(f"{want} is not in {a.frozen}")
    s = next((x for x in mine if x["name"] == want), None)
    if s is None:
        sys.exit(f"{want} is not a sprint on board {a.board}")
    d = sprint_detail(a.board, s, a.project)
    fields = [("items", 3), ("items_done", 4), ("committed", 5), ("final", 6), ("completed", 7)]
    print(f"--- selfcheck {want} ------------------------------------")
    print(f"{'field':<12}{'frozen':>9}{'now':>9}   verdict")
    bad = 0
    for key, idx in fields:
        now, was = d[key], row[idx]
        ok = (now == was)
        bad += (not ok)
        print(f"{key:<12}{was:>9}{now:>9}   {'match' if ok else 'DIFFERS'}")
    sp_ = d["spill"]; fs = fz.get("SPILL", {}).get(want) or {}
    if fs:
        print(f"{'spill.open':<12}{str(fs['open']):>9}{str([sp_['open_items'], round(sp_['open_pts'])]):>9}")
        print(f"{'spill.out':<12}{str(fs['out']):>9}{str([sp_['out_items'], round(sp_['out_pts'])]):>9}")
    print("A closed sprint keeps only what finished in it, so a sprint frozen while it")
    print("was still open is EXPECTED to differ here. One frozen after it closed is not.")
    print(f"--- {bad} field(s) differ -------------------------------")


if __name__ == "__main__":
    main()
