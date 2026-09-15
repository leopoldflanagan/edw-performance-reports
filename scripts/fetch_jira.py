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


def _left_sprint(i, name):
    """When this issue was last removed from that sprint, if it ever was.
    This is the event that makes a closed sprint look cleaner than it was:
    the work leaves, and with it the record that it had been committed."""
    out = None
    for h in i.get("changelog", {}).get("histories", []):
        for it in h["items"]:
            if it["field"] != "Sprint": continue
            to  = [x.strip() for x in (it.get("toString")   or "").split(",")]
            frm = [x.strip() for x in (it.get("fromString") or "").split(",")]
            d = dt.datetime.fromisoformat(h["created"].replace("Z", "+00:00"))
            if name in to and name not in frm:
                out = None            # it came back in
            elif name in frm and name not in to:
                if out is None or d > out: out = d
    return out

def sprint_detail(board, sp, project):
    """Rebuilds a sprint from its own history.

    The one thing that makes this different from reading Jira's board: a sprint that
    is closed keeps only what finished inside it. EDW empties its sprints first, so
    asking `sprint = N` gives back the completed work and nothing else — which makes
    the day-1 commitment shrink retroactively along with the scope, and every sprint
    read as if it had over-delivered. Everything below is computed over the sprint's
    real membership: what is still in it PLUS what was removed before it closed.
    """
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

    # ---- Jira's own sprint report, first: it is what names the removed issues
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
        pass   # a closed-sprint report can be unavailable; the rest still works

    issues_all = list(issues)
    if punted:
        have = {i["key"] for i in issues}
        extra = search(f'key in ({", ".join(punted)})',
                       ["status", "summary", SP_FIELD, "resolutiondate", "labels", "issuetype"],
                       expand="changelog")
        issues_all += [i for i in extra if i["key"] not in have]

    # ---- the accounting, over the real membership
    rows, committed, final, completed, items_done = [], 0.0, 0.0, 0.0, 0
    for i in issues_all:
        v = sp_of(i)
        e = entered(i) or start          # no Sprint event = it was there from the start
        o = _left_sprint(i, name)
        d = done_at(i)
        final += v
        if e <= day1:
            committed += v               # committed even if it was pulled out later
        if d is not None and d <= horizon and (o is None or d <= o):
            completed += v; items_done += 1
        rows.append((e, v, d, o))

    days = max(1, int((horizon - start).total_seconds() // 86400) + 1)
    burn, scope, ghost = [], [], []
    for k in range(days + 1):
        t = start + dt.timedelta(days=k)
        inside = lambda e, o: e <= t and (o is None or o > t)
        scope.append(round(sum(v for e, v, _d, o in rows if inside(e, o)), 1))
        burn.append(round(sum(v for e, v, d, o in rows
                              if inside(e, o) and not (d and d <= t)), 1))
        # what would still be open if nothing had been taken out of the sprint
        ghost.append(round(sum(v for e, v, d, _o in rows
                               if e <= t and not (d and d <= t)), 1))

    dist = {}
    for i in issues:
        st = i["fields"]["status"]["name"]
        dist[st] = dist.get(st, 0) + 1

    gone = spill["open_pts"] + spill["out_pts"]
    allp = spill["done_pts"] + gone
    elapsed = (now - start).total_seconds() / max(1, (end - start).total_seconds())
    pct_elapsed = min(100, round(100*elapsed))

    return {
        "name": name, "state": sp["state"],
        "start": sp["startDate"][:10], "end": (end_s or "")[:10],
        "goal": (sp.get("goal") or "").strip(),
        "items": len(issues_all), "items_done": items_done,
        "committed": round(committed), "final": round(final), "completed": round(completed),
        "scope_change": round(100*(final-committed)/committed) if committed else None,
        "vs_commitment": round(100*completed/committed) if committed else None,
        "time_elapsed": pct_elapsed,
        "spill": spill,
        # spillover only means something once the sprint is near its end: three days in,
        # "95% not finished" is a statement about the calendar, not about the team
        "spill_rate": (round(100*gone/allp) if allp else None) if pct_elapsed >= 80 else None,
        "dist": dist, "burn": burn, "scope": scope, "ghost": ghost,
        "_issues": issues, "_issues_all": issues_all,
        "_start": start, "_end": end, "_day1": day1,
    }
def _clean(d):
    """Strip the raw payload the month block needs but the panel must not carry."""
    return {k: v for k, v in d.items() if not k.startswith("_")}

def month_so_far(project, window=None, label=None, key=None):
    """What has closed in the period in progress. The period is the current release
    when one is given, and the calendar month only as a fallback -- mixing the two
    in one card is what made day 15 of September sit next to day 2 of the sprint."""
    today = dt.date.today()
    if window:
        first = dt.date.fromisoformat(window[0])
        nxt   = dt.date.fromisoformat(window[1]) + dt.timedelta(days=1)
    else:
        first = today.replace(day=1)
        nxt   = (first + dt.timedelta(days=32)).replace(day=1)
    base  = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
             f'AND resolution = Done AND resolved >= "{first}" AND resolved < "{nxt}"')
    iss   = search(base, ["resolutiondate", SP_FIELD, "labels", "issuetype", "assignee"])
    unp   = sum(1 for i in iss
                if any(l.lower() in ("unplanned", "not planned", "not_planned")
                       for l in i["fields"].get("labels", []))
                or i["fields"]["issuetype"]["name"] == "Urgent Task")
    # EDW does not apply the Unplanned label, so "no item carries a reactive
    # marker" means the question was never asked, not that no reactive work
    # happened. Reading that as 0% is the false-zero the reports warn about;
    # any other label being present does not make THIS one measured.
    labelled = unp > 0
    dar   = sum(1 for i in iss if any("access" in l.lower() for l in i["fields"].get("labels", [])))
    pts   = sum(sp_of(i) for i in iss)
    people = {}
    for i in iss:
        a = (i["fields"].get("assignee") or {}).get("displayName")
        if a: people[a] = people.get(a, 0) + 1
    day  = max(1, min((today - first).days + 1, (nxt - first).days))
    return {"month": key or first.strftime("%Y-%m"),
            "label": label or first.strftime("%B %Y"),
            "kind": "release" if window else "month",
            "start": first.isoformat(), "end": (nxt - dt.timedelta(days=1)).isoformat(),
            "day": day, "days": (nxt - first).days,
            "closed": len(iss), "points": round(pts),
            "unplanned": unp if labelled else None,
            "unplanned_pct": (round(100*unp/len(iss), 1) if iss else None) if labelled else None,
            "access_requests": dar,
            "people_active": sum(1 for _, c in people.items() if c >= 2)}


SIGNOFF_PAGE = (os.environ.get("SIGNOFF_PAGE") or "3746431012").strip()   # EDW register; DS/LL override via env


def _soft(path):
    """A GET that returns None instead of killing the run. Confluence is an input,
    not a dependency: if it cannot be read the reports stay pending, which is the
    safe direction to fail in."""
    try:
        req = request.Request(BASE + path, headers=HDRS, method="GET")
        with request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  note: could not read {path} ({e.__class__.__name__}) - "
              f"continuing without it", flush=True)
        return None


def signoff(page_id):
    """Who has signed off which report, read from the Confluence sign-off register.

    A report counts as reviewed only when BOTH tasks in its row are complete: the
    Scrum Master, who confirms the data is right, and the team owner, who confirms
    the reading is right.

    The signature is the Confluence account that ticked the box, and the page's own
    version history is the audit trail. That is the entire reason this does not live
    in a file in this repository, where the reviewer's name was free text that anyone
    could type -- that recorded a claim, not a signature.
    """
    if not page_id:
        return None
    import re
    p = _soft(f"/wiki/api/v2/pages/{page_id}?body-format=storage")
    if not p:
        return None
    html = (((p.get("body") or {}).get("storage") or {}).get("value")) or ""
    ver  = (p.get("version") or {})
    names = {}

    def who(aid):
        if aid not in names:
            u = _soft("/wiki/rest/api/user?accountId=" + parse.quote(aid))
            names[aid] = (u or {}).get("displayName") or "someone"
        return names[aid]

    out = {}
    for row in re.split(r"<tr[ >]", html):
        m = re.search(r"<code>([^<]+\.html)</code>", row)
        if not m:
            continue
        slug   = m.group(1).strip()
        states = re.findall(r"<ac:task-status>(\w+)</ac:task-status>", row)
        ids    = re.findall(r'ri:account-id="([^"]+)"', row)
        done   = [a for a, st in zip(ids, states) if st == "complete"]
        entry  = {"page": page_id,
                  "url": f"{BASE}/wiki/spaces/EDW/pages/{page_id}",
                  "version": ver.get("number"), "checked": len(done), "of": len(states)}
        if states and len(done) == len(states):
            entry["status"] = "reviewed"
            entry["by"]     = " and ".join(who(a) for a in done)
            entry["date"]   = (ver.get("createdAt") or "")[:10]
        else:
            entry["status"] = "pending"
            entry["waiting_on"] = [who(a) for a, st in zip(ids, states) if st != "complete"]
        out[slug] = entry
    print(f"  sign-off register: {sum(1 for v in out.values() if v['status']=='reviewed')}"
          f" of {len(out)} reports signed by both", flush=True)
    return out


PARKED = {"Backlog", "Deferred"}   # layer 3 and layer 4 of the backlog guide: not in flow
STALE_AGE = 7    # calendar days in one status before open work counts as stuck


def aging(project, window_days=90):
    """Two questions about the same workflow, answered from one pass of changelog.

    aging   - for work that is open RIGHT NOW: how long it has been sitting in the
              status it is in. This is where work is piling up.
    clearing- for transitions that already happened in the window: how long items
              took to get THROUGH each status. This is how fast work moves.

    They are not the same number and the gap between them is the finding: a status
    that clears in a day but holds fifteen items is a queue, not a slow step.
    Backlog is reported apart - waiting to be pulled is not a workflow bottleneck.
    """
    since_d = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
    jql = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
           f'AND (statusCategory != Done OR resolved >= "{since_d}")')
    iss = search(jql, ["status", "summary", "created", "issuetype", "assignee"],
                 expand="changelog", cap=8)
    now = dt.datetime.now(dt.timezone.utc)
    open_in, cleared = {}, {}
    for i in iss:
        st_now = i["fields"]["status"]["name"]
        moves = []
        for h in i.get("changelog", {}).get("histories", []):
            for it in h["items"]:
                if it["field"] == "status":
                    moves.append((_dtp(h["created"]), it.get("fromString"), it.get("toString")))
        moves.sort()
        cur   = moves[0][1] if moves else st_now
        since = _dtp(i["fields"]["created"])
        for when, _f, to in moves:
            cleared.setdefault(cur, []).append(max(0.0, (when - since).total_seconds()/86400))
            cur, since = to, when
        if st_now not in TERMINAL:
            open_in.setdefault(st_now, []).append(
                (round(max(0.0, (now - since).total_seconds()/86400), 1),
                 i["key"], (i["fields"].get("summary") or "")[:90],
                 (i["fields"].get("assignee") or {}).get("displayName") or "unassigned"))

    # Per the team's own Backlog Organization Guide, Deferred is layer 4 -- archived,
    # deliberately not mapped to any board column -- and Backlog is layer 3, waiting to
    # be defined. Neither is work moving through the workflow, and counting them here
    # buried the real bottleneck under 75 archived items aged 280 days.
    parked_counts = {}
    # every status the workflow actually uses, so a step with nothing in it still shows
    # as a row rather than silently disappearing
    seen = set(open_in) | set(cleared)
    rows = []
    for st in seen:
        if st in TERMINAL or st in PARKED:
            if st in open_in:
                parked_counts[st] = len(open_in[st])
            continue
        xs = open_in.get(st) or []
        cl = cleared.get(st) or []
        if not xs and not cl:
            continue
        if not xs:
            rows.append({"status": st, "open": 0, "med_age": 0, "max_age": 0,
                         "worst_key": "", "worst_sum": "", "worst_who": "", "over": 0,
                         "clear_med": round(_median(cl), 1), "clear_n": len(cl)})
            continue
        ages  = sorted(x[0] for x in xs)
        worst = max(xs)
        rows.append({"status": st, "open": len(xs),
                     "med_age": round(_median(ages), 1), "max_age": worst[0],
                     "worst_key": worst[1], "worst_sum": worst[2], "worst_who": worst[3],
                     "over": sum(1 for a in ages if a >= STALE_AGE),
                     "clear_med": round(_median(cl), 1) if cl else None,
                     "clear_n": len(cl)})
    # queue pressure: how many are waiting times how long they have waited
    rows.sort(key=lambda r: -(r["med_age"] * r["open"]))
    live = [r for r in rows if r["open"]]
    return {"window_days": window_days, "stale_days": STALE_AGE, "rows": rows,
            "parked": parked_counts, "open_total": sum(r["open"] for r in rows),
            "stale": sum(r["over"] for r in rows),
            "worst": live[0]["status"] if live else None}


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
    """A sprint belongs to the month it ENDS in — the rule the closed months use."""
    out = []
    for s in mine:
        e = s.get("completeDate") or s.get("endDate")
        if e and e[:7] == ym and s["state"] != "future":
            out.append(s)
    return sorted(out, key=lambda s: s.get("completeDate") or s["endDate"])

def current_release(frozen_path):
    """The release whose window contains today, from the calendar in frozen.json.
    Falls back to the last one when today sits past the end of the table."""
    try:
        rel = json.load(open(frozen_path)).get("RELEASES") or {}
    except Exception:
        return None
    if not rel:
        return None
    today = dt.date.today().isoformat()
    for k in sorted(rel):
        if rel[k]["start"] <= today <= rel[k]["end"]:
            return k, rel[k]
    k = sorted(rel)[-1]
    return k, rel[k]

def sprints_named(mine, names):
    """The board's sprints matching a release's sprint list, in order, skipping
    any that have not started."""
    want = {n: i for i, n in enumerate(names)}
    out = [s for s in mine if s["name"] in want and s["state"] != "future"]
    return sorted(out, key=lambda s: want[s["name"]])

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

def month_block(board, project, team, mine, ym, prev_closed=None, window=None, sprint_names=None, label=None):
    if window:
        first = dt.date.fromisoformat(window[0])
        nxt   = dt.date.fromisoformat(window[1]) + dt.timedelta(days=1)
        label = label or ym
        m     = ym          # a release keys CAP/CYC by its own number, not by month
    else:
        y, m = ym.split("-")
        first = dt.date(int(y), int(m), 1)
        nxt   = (first + dt.timedelta(days=32)).replace(day=1)
        label = f"{MONTH_NAMES[int(m)-1]} {y}"

    rows, spill, split, tis, ghost, names = {}, {}, {}, {}, {}, []
    for s in (sprints_named(mine, sprint_names) if sprint_names else sprints_of_month(mine, ym)):
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
        ghost[n] = d["ghost"]
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
        "month": {"slug": (f"2026-r{ym.replace('.','')}" if window
                           else f"{first.year}-{first:%m}-{MONTH_NAMES[first.month-1].lower()}"),
                  "label": label,
                  "short": (ym if window else MONTH_NAMES[first.month-1][:3].upper()),
                  "n_sprints": len(sprint_names or []) or None,
                  "start": first.isoformat(), "end": (nxt - dt.timedelta(days=1)).isoformat(),
                  "prev": MONTH_NAMES[first.month-2] if not window else "",
                  "prev_closed": prev_closed,
                  "closed": cap[0], "discarded": discarded,
                  "resolved": cap[0] + discarded,
                  "unplanned": unp, "unp_pct": unp_pct,
                  "types": sorted(types.items(), key=lambda kv: -kv[1]),
                  "sprints": names, "unp_items": unp_items,
                  "open": open_month, "day": today.day, "days": days,
                  "status": status, "headline": headline, "notes": notes},
        "SPRINTS": [rows[n] for n in names],
        "SPILL": spill, "SPLIT": split, "TIS": tis, "GHOST": ghost,
        "CAP": {m: cap}, "CYC": {m: cyc},
        "complete": all(s["state"] == "closed"
                        for s in (sprints_named(mine, sprint_names) if sprint_names
                                  else sprints_of_month(mine, ym)))
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
    live_sp = _clean(det) if det else None
    if live_sp and live_sp.get("start") and live_sp.get("end"):
        # one number for "how far in are we", used by the tiles and the burndown
        _s = dt.date.fromisoformat(live_sp["start"][:10])
        _e = dt.date.fromisoformat(live_sp["end"][:10])
        live_sp["days"] = max(1, (_e - _s).days)
        live_sp["day"]  = max(1, min((dt.date.today() - _s).days + 1, live_sp["days"]))

    # the period in progress, in the unit the reports now use: the release
    cur = current_release(a.frozen)
    if cur:
        _rk, _r = cur
        period = month_so_far(a.project, window=(_r["start"], _r["end"]),
                              label=_r.get("label") or f"Release {_rk}", key=_rk)
        # a release is measured in sprints, not in calendar days: "day 16 of 28"
        # sitting next to a sprint's "day 2 of 14" reads like a contradiction
        _state = {x["name"]: x["state"] for x in mine}
        period["sprints"]      = _r["sprints"]
        period["n_sprints"]    = len(_r["sprints"])
        period["sprints_done"] = sum(1 for n in _r["sprints"] if _state.get(n) == "closed")
    else:
        period = month_so_far(a.project)

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "team": a.team, "board": a.board, "kind": kind,
        "sprint": live_sp,
        "next": ({"name": future[0]["name"], "start": future[0]["startDate"][:10],
                  "state": "not started"} if future else None),
        "month": period,
        "aging": aging(a.project),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{a.out}: {kind} {out['sprint']['name'] if out['sprint'] else '-'} - "
          f"month {out['month']['closed']} closed")

    # the month in progress, in the same shape the frozen months use
    # The period in progress is the release whose window contains today. Falls back
    # to the calendar month only if the release table is missing.
    if cur:
        rk, r = cur
        prev_closed = None
        try:
            fz = json.load(open(a.frozen))
            keys = sorted(fz.get("RELEASES", {}))
            i = keys.index(rk)
            if i:
                p = fz["RELEASES"][keys[i-1]]
                prev_closed = round(p["closed"] / p["n_sprints"] * len(r["sprints"]))
        except Exception:
            pass
        blk = month_block(a.board, a.project, a.team, mine, rk, prev_closed,
                          window=(r["start"], r["end"]), sprint_names=r["sprints"],
                          label=f"Release {rk}")
        blk["kind"] = "release"
        blk["n_sprints"] = len(r["sprints"])
    else:
        ym = dt.date.today().strftime("%Y-%m")
        prev_closed = None
        try:
            fz = json.load(open(a.frozen))
            pm = (dt.date.today().replace(day=1) - dt.timedelta(days=1)).strftime("%m")
            prev_closed = (fz.get("CAP", {}).get(pm) or [None])[0]
        except Exception:
            pass
        blk = month_block(a.board, a.project, a.team, mine, ym, prev_closed)
        blk["kind"] = "month"
    with open(a.month_out, "w") as f:
        json.dump(blk, f, indent=1)

    # the sign-off register. Written here rather than hand-edited, so the only way
    # a report turns green is that both people ticked their own box in Confluence.
    sg = signoff(SIGNOFF_PAGE)
    if sg is not None:
        with open(os.path.join(os.path.dirname(a.out) or ".", "review.json"), "w") as f:
            json.dump(sg, f, indent=1, ensure_ascii=False)
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
