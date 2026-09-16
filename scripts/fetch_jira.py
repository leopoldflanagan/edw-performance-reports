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
            if prev and _entered_sprint(i, prev) is not None:
                recv_items += 1; recv_pts += v
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


CAPACITY_PAGE = (os.environ.get("CAPACITY_PAGE") or "3747938305").strip()   # EDW; DS/LL override via env

_ENT = {"&nbsp;": " ", "&mdash;": "-", "&ndash;": "-", "&amp;": "&", "&lt;": "<",
        "&gt;": ">", "&quot;": '"', "&#39;": "'", "&iacute;": "i", "&oacute;": "o",
        "&aacute;": "a", "&eacute;": "e", "&uacute;": "u", "&ntilde;": "n"}


def _cell(x):
    """One table cell as plain text. A Confluence date node keeps its ISO value
    rather than the way it happens to be displayed."""
    import re as _re
    x = _re.sub(r'<time[^>]*datetime="([^"]+)"[^>]*/?>', r"\1", x)
    x = _re.sub(r"<[^>]+>", "", x)
    for k, v in _ENT.items():
        x = x.replace(k, v)
    return x.strip()


def _tables(html):
    """Every table on a Confluence page as a list of header-keyed rows.

    Cells are matched by HEADER NAME, never by position. That promise is written
    on the capacity page itself, so someone can add or reorder a column there
    without anyone touching this file.
    """
    import re as _re
    out = []
    for t in html.split("<table")[1:]:
        rows = [[_cell(c) for c in _re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", r)]
                for r in _re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", t)]
        rows = [r for r in rows if r]
        if not rows:
            continue
        hdr = rows[0]
        out.append({"headers": hdr,
                    "rows": [{k: (r[i] if i < len(r) else "") for i, k in enumerate(hdr)}
                             for r in rows[1:]]})
    return out


def _num(x):
    try:
        return float(str(x).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _sprint_name(x):
    """'EDW-Sprint 25-26 (not in Jira yet)' -> 'EDW-Sprint 25-26'."""
    import re as _re
    m = _re.search(r"[A-Za-z]+-Sprint\s+\d+-\d+", x or "")
    return m.group(0) if m else None


def capacity(page_id):
    """Team capacity, sprint goals and the roster, from the Confluence page.

    This is the one input to the reports that a human maintains, so it is read
    forgivingly: a missing page, a renamed column or an empty cell costs that one
    fact and nothing else. The reports have always been able to render without
    capacity, and they still can.
    """
    if not page_id:
        return None
    p = _soft(f"/wiki/api/v2/pages/{page_id}?body-format=storage")
    if not p:
        return None
    html = (((p.get("body") or {}).get("storage") or {}).get("value")) or ""
    T = _tables(html)

    def find(*must):
        for t in T:
            if all(any(m.lower() in h.lower() for h in t["headers"]) for m in must):
                return t
        return None

    out = {"page": page_id, "url": f"{BASE}/wiki/spaces/EDW/pages/{page_id}",
           "sprints": {}, "goals": {}, "roster": [], "config": {}, "changes": []}

    cap = find("Sprint", "Capacity %")
    for r in (cap or {}).get("rows", []):
        n = _sprint_name(r.get("Sprint"))
        if not n:
            continue
        out["sprints"][n] = {
            "release":   (r.get("Release") or "").strip() or None,
            "start":     r.get("Start") or None, "end": r.get("End") or None,
            "members":   _num(r.get("Team members")),
            "holidays":  _num(r.get("Holidays")),
            "pto":       _num(r.get("Team PTO (days)")),
            "eff_days":  _num(r.get("Effective days")),
            "pct":       _num(r.get("Team Capacity %")),
            "risk":      (r.get("Capacity Risk") or "").strip() or None,
            "planned":   "not in Jira yet" in (r.get("Sprint") or ""),
        }

    gl = find("Sprint", "Sprint Goal")
    for r in (gl or {}).get("rows", []):
        n = _sprint_name(r.get("Sprint"))
        g = (r.get("Sprint Goal") or "").strip()
        c = _num(r.get("Committed (pts)"))
        if n and (g or c is not None):
            out["goals"][n] = {"goal": g or None, "committed": c,
                               "notes": (r.get("Notes") or "").strip() or None}

    ros = find("Person")
    for r in (ros or {}).get("rows", []):
        who = (r.get("Person") or "").strip()
        if who:
            out["roster"].append({"name": who, "role": (r.get("Role") or "").strip() or None,
                                  "status": (r.get("Status") or "").strip()})
    out["team"] = [p for p in out["roster"]
                   if not (p["status"] or "").lower().startswith(("former", "left"))]

    ch = find("From sprint", "What changed")
    for r in (ch or {}).get("rows", []):
        n = _sprint_name(r.get("From sprint"))
        what = (r.get("What changed") or "").strip()
        if n and what:
            out.setdefault("changes", []).append({
                "sprint": n, "date": (r.get("Date") or "").strip() or None,
                "what": what,
                "affects": [x.strip().lower() for x in (r.get("Affects") or "").split(",") if x.strip()],
                "effect": (r.get("Expected effect on the numbers") or "").strip() or None})

    cfg = find("Variable", "Value")
    for r in (cfg or {}).get("rows", []):
        k = (r.get("Variable") or "").strip()
        if k:
            out["config"][k] = (r.get("Value") or "").strip()

    print(f"  capacity page: {len(out['sprints'])} sprint rows, "
          f"{len(out['goals'])} goal(s), {len(out['roster'])} people, "
          f"{len(out['changes'])} practice change(s)", flush=True)
    return out


GROOM_FIELD = os.environ.get("JIRA_GROOM_FIELD", "customfield_10176")   # Grooming Status
READY_STATUS = "Ready for Development"
GROOMED      = "7-Groomed"


def backlog(project, frozen_path):
    """How much ready work is waiting, measured in sprints of runway.

    Layer 2 of the team's Backlog Organization Guide is the definition: status
    'Ready for Development' AND Grooming Status '7-Groomed' AND not already in an
    open sprint. The guide also forbids certain combinations, so the same pass
    checks them -- the rule and its own violations come from one source.

    Everything is computed here from ONE query rather than several JQL counts,
    because the dropdown's JQL name is easy to get subtly wrong and a miscounted
    backlog is worse than none.
    """
    iss = search(f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) '
                 f'AND statusCategory != Done',
                 ["status", SP_FIELD, GROOM_FIELD, "summary"], cap=6)
    if not iss:
        return None

    def groom(i):
        v = i["fields"].get(GROOM_FIELD)
        if isinstance(v, dict): v = v.get("value")
        return (v or "").strip()

    def pts(i):
        return sp_of(i)

    ready, misfiled, draft_in_ready, groomed_gone, no_est = [], [], [], [], []
    for i in iss:
        st, g = i["fields"]["status"]["name"], groom(i)
        if st == READY_STATUS and g.startswith("7"):
            ready.append(i)
            if i["fields"].get(SP_FIELD) is None: no_est.append(i)
        elif st == "Backlog" and g.startswith("7"):
            misfiled.append(i)          # the guide: an item cannot be Groomed and stay in Backlog
        elif st == READY_STATUS and g.startswith("1"):
            draft_in_ready.append(i)    # the guide: Idea/Draft cannot be Ready for Development
        if st == "Deferred" and g.startswith("7"):
            groomed_gone.append(i)      # groomed work that was archived

    # the denominator: points actually delivered per sprint, from the closed releases
    per = None
    try:
        fz = json.load(open(frozen_path))
        rel = [v for k, v in sorted(fz.get("RELEASES", {}).items()) if not v.get("open")]
        rates = [v["points"] / v["n_sprints"] for v in rel[-3:]
                 if v.get("points") and v.get("n_sprints")]
        per = round(sum(rates) / len(rates), 1) if rates else None
    except Exception:
        per = None

    P = lambda xs: round(sum(pts(i) for i in xs))
    ready_p, mis_p = P(ready), P(misfiled)
    run     = round(ready_p / per, 1) if per else None
    run_fix = round((ready_p + mis_p) / per, 1) if per else None

    def band(r):
        if r is None: return None
        return "Skinny" if r < 1.5 else ("In shape" if r <= 2.5 else "Fat")

    return {
        "per_sprint_pts": per,
        "bands": {"skinny": "< 1.5 sprints", "in_shape": "1.5 to 2.5 sprints", "fat": "> 2.5 sprints"},
        "ready":    {"items": len(ready), "points": ready_p},
        "misfiled": {"items": len(misfiled), "points": mis_p},
        "runway": run, "runway_if_fixed": run_fix,
        "state": band(run), "state_if_fixed": band(run_fix),
        "violations": [
            {"rule": "Groomed but still in Backlog", "n": len(misfiled), "points": mis_p,
             "why": "the guide: an item cannot be Groomed and remain in Backlog. "
                    "This work is ready and invisible to planning."},
            {"rule": "Idea/Draft sitting in Ready for Development", "n": len(draft_in_ready),
             "points": P(draft_in_ready),
             "why": "the guide: Idea/Draft cannot be Ready for Development. "
                    "It counts as ready to pull when it is not defined."},
            {"rule": "Groomed items with no estimate", "n": len(no_est), "points": 0,
             "why": "the guide: a Groomed item must be estimated."},
            {"rule": "Groomed work archived as Deferred", "n": len(groomed_gone),
             "points": P(groomed_gone),
             "why": "work that met Definition of Ready and was then parked."},
        ],
    }


F_TARGET_END = os.environ.get("JIRA_TARGET_END", "customfield_10023")
ADHOC        = "8-AdHoc"
LONG_HAUL    = 4          # sprints an item can ride before it is worth naming


def admin(project, live_sp, cap_page):
    """Administrative hygiene, split by what it actually costs.

    BLOCKING is the Definition of Ready exactly as the team's Backlog Organization
    Guide writes it. The gate is not the sprint, it is *Ready for Development*: an
    item that reaches that status without meeting DoR is a planning problem one
    step before anyone notices it in a sprint.

    DEBT is everything that helps reporting but does not stop the sprint.

    One rule keeps this honest: a field missing on nearly every item is reported as
    a field the team does not use, not as N separate warnings. A check that is
    always red is not a check, and a page where everything is red says nothing.
    """
    active = (live_sp or {}).get("name")
    jql = (f'project = "{project}" AND issuetype NOT IN (Sub-task, Epic) AND ('
           f'status = "{READY_STATUS}"'
           + (f' OR sprint = "{active}"' if active else "") + ")")
    iss = search(jql, ["status", "summary", "assignee", "fixVersions", "timetracking",
                       "labels", "issuetype", "issuelinks", SP_FIELD, GROOM_FIELD,
                       F_TARGET_END, "sprint"], cap=6)
    if not iss:
        return None

    def groom(i):
        v = i["fields"].get(GROOM_FIELD)
        if isinstance(v, dict): v = v.get("value")
        return (v or "").strip()

    def in_sprint(i):
        return active and any((s or {}).get("name") == active
                              for s in (i["fields"].get("sprint") or []))

    roster = {p["name"] for p in ((cap_page or {}).get("roster") or [])
              if not (p.get("status") or "").lower().startswith("left")}

    def ref(i):
        return {"key": i["key"], "summary": (i["fields"].get("summary") or "")[:80]}

    B, D = [], []          # blocking, debt
    def add(bucket, rule, why, items, total=None):
        if items:
            bucket.append({"rule": rule, "why": why, "n": total or len(items),
                           "items": [ref(i) for i in items[:8]]})

    ready = [i for i in iss if i["fields"]["status"]["name"] == READY_STATUS]
    sprint = [i for i in iss if in_sprint(i)]
    gate = {i["key"]: i for i in ready + sprint}.values()

    # ---- blocking: the Definition of Ready ---------------------------------
    add(B, "No estimate",
        "the guide: a Groomed item must be estimated. Ready for Development without "
        "story points means planning is committing to an unknown.",
        [i for i in gate if i["fields"].get(SP_FIELD) is None])
    add(B, "No Grooming Status",
        "an item in Ready for Development with no grooming status has not been through "
        "refinement, whatever its column says.",
        [i for i in ready if not groom(i)])
    add(B, "Idea/Draft in Ready for Development",
        "the guide does not allow it: it counts as ready to pull when it is not defined.",
        [i for i in ready if groom(i).startswith("1")])
    add(B, "AdHoc without the unplanned label",
        "the guide does not allow it. Unlabelled reactive work is why the reactive "
        "share cannot be measured.",
        [i for i in gate if groom(i).startswith("8")
         and not any(l.lower() == "unplanned" for l in i["fields"].get("labels", []))])
    add(B, "No assignee in the active sprint",
        "work in the sprint that nobody owns.",
        [i for i in sprint if not i["fields"].get("assignee")])
    _blocked = [i for i in gate
                if any("block" in (l.get("type", {}).get("name", "")).lower()
                       and ((l.get("inwardIssue") or l.get("outwardIssue") or {})
                            .get("fields", {}).get("status", {})
                            .get("statusCategory", {}).get("key") != "done")
                       for l in (i["fields"].get("issuelinks") or []))]
    add(B, "Open dependency", "the guide: Definition of Ready means no open dependencies.", _blocked)
    add(B, "Still in Backlog inside the sprint",
        "in the sprint but never pulled into the flow.",
        [i for i in sprint if i["fields"]["status"]["name"] == "Backlog"])

    # ---- debt: useful, not blocking ----------------------------------------
    def coverage(items, ok):
        """A field nobody fills is one finding, not many."""
        bad = [i for i in items if not ok(i)]
        return bad, (len(bad) / len(items) if items else 0)

    for rule, why, ok in (
        ("No fix version", "the release a delivery belongs to cannot be traced without it.",
         lambda i: i["fields"].get("fixVersions")),
        ("No original estimate", "time tracking is empty, so effort cannot be compared to points.",
         lambda i: (i["fields"].get("timetracking") or {}).get("originalEstimate")),
        ("No Target end date", "there is no expected date to measure a slip against.",
         lambda i: i["fields"].get(F_TARGET_END)),
    ):
        bad, share = coverage(list(gate), ok)
        if share >= 0.8:
            D.append({"rule": rule.replace("No ", "").capitalize() + " is not in use",
                      "why": f"missing on {len(bad)} of {len(list(gate))} items. This reads as a "
                             f"field the team does not use rather than {len(bad)} oversights. "
                             f"Worth deciding: adopt it or stop asking for it.",
                      "n": len(bad), "items": []})
        else:
            add(D, rule, why, bad)

    if roster:
        add(D, "Assignee is not on the roster",
            "the capacity page lists the team; this work is assigned outside it.",
            [i for i in sprint
             if (i["fields"].get("assignee") or {}).get("displayName")
             and (i["fields"]["assignee"]["displayName"]) not in roster])

    add(D, f"Riding {LONG_HAUL}+ sprints",
        "an item that keeps moving forward is not spillover, it is a decision nobody has made.",
        [i for i in gate if len(i["fields"].get("sprint") or []) >= LONG_HAUL])

    # ---- sprint-level ------------------------------------------------------
    setup = []
    if live_sp and not (live_sp.get("goal") or "").strip():
        setup.append({"rule": "The active sprint has no goal",
                      "why": "neither Jira nor the capacity page records one, so delivery "
                             "can only be measured in points.", "n": 1, "items": []})
    if cap_page and active and active not in (cap_page.get("sprints") or {}):
        setup.append({"rule": "The sprint is missing from the capacity page",
                      "why": "the planning record and Jira have drifted apart.",
                      "n": 1, "items": []})

    print(f"  admin checks: {sum(x['n'] for x in B)} blocking, "
          f"{sum(x['n'] for x in D)} debt, {len(setup)} sprint setup", flush=True)
    return {"scope": {"ready": len(ready), "sprint": len(sprint), "sprint_name": active},
            "blocking": B, "debt": D, "setup": setup}


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
        d = sprint_detail(board, s, project, prev=_prev_sprint(mine, s))
        n = d["name"]; names.append(n)
        st, en = _dtp(s["startDate"]), _dtp(s.get("completeDate") or s["endDate"])
        rows[n] = [n, _mday(st), _mday(en), d["items"], d["items_done"],
                   d["committed"], d["final"], d["completed"],
                   d["scope_change"] if d["scope_change"] is not None else 0,
                   d["burn"], d["scope"]]
        sp_ = d["spill"]
        _rc = d.get("recv") or {}
        spill[n] = {"done": [d["items_done"], round(sp_["done_pts"])],
                    "open": [sp_["open_items"], round(sp_["open_pts"])],
                    "out":  [sp_["out_items"],  round(sp_["out_pts"])],
                    # the other side of the transfer: what this sprint inherited
                    "in":   [_rc.get("items", 0), _rc.get("pts", 0)],
                    "in_pct": _rc.get("pct"), "in_from": _rc.get("from")}
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

    det = sprint_detail(a.board, sp, a.project, prev=_prev_sprint(mine, sp)) if sp else None
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

    cap_page = capacity(CAPACITY_PAGE)
    if live_sp and cap_page:
        # the page is the planning record; Jira is the execution record. Where Jira
        # has no goal, the one agreed at planning is better than nothing, and it is
        # labelled so nobody mistakes where it came from.
        live_sp["capacity"] = (cap_page["sprints"] or {}).get(live_sp["name"])
        _g = (cap_page["goals"] or {}).get(live_sp["name"]) or {}
        if not live_sp.get("goal") and _g.get("goal"):
            live_sp["goal"] = _g["goal"]
            live_sp["goal_src"] = "capacity page"
        if _g.get("committed") is not None:
            live_sp["committed_planned"] = _g["committed"]

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "team": a.team, "board": a.board, "kind": kind,
        "capacity": cap_page,
        "backlog": backlog(a.project, a.frozen),
        "admin": admin(a.project, live_sp, cap_page),
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
        if cap_page:
            # every sprint the page knows, not only this release's: a closed sprint
            # on an older report should still be able to show what it was planned with
            blk["CAPACITY"] = cap_page["sprints"]
            blk["GOALS"]    = cap_page["goals"]
            blk["ROSTER"]   = cap_page["roster"]
            blk["CHANGES"]  = cap_page["changes"]
            blk["CAP_URL"]  = cap_page["url"]
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
    # (capacity is attached to the block above, see main())
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
    d = sprint_detail(a.board, s, a.project, prev=_prev_sprint(mine, s))
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
