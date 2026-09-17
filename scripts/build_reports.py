#!/usr/bin/env python3
"""
Builds the delivery report pages. The team is configured, not hardcoded: see TEAM.

Everything the pages need comes from two files, never from constants in here:

  data/frozen.json  periods that are already closed and published. Never recomputed.
  data/live.json    what fetch_jira.py pulled from Jira on this run: the sprint that is
                    open (or the last one that closed) and the month in progress.

  python3 scripts/build_reports.py --all        rebuild every page
  python3 scripts/build_reports.py --current    only the month in progress + the index
"""
import os, sys, json, argparse, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_ap = argparse.ArgumentParser()
_ap.add_argument("--all", action="store_true", help="rebuild every page")
_ap.add_argument("--current", action="store_true", help="only the month in progress")
_ap.add_argument("--root", default=ROOT)
ARGS = _ap.parse_args()

REPO = ARGS.root
DATA = json.load(open(os.path.join(REPO, "data", "frozen.json")))
globals().update(DATA)
GHOST = DATA.setdefault("GHOST", {})
_FROZEN_MONTHS = set(DATA.get("MONTHS", {}))   # before the merge below mutates it

CSS = open(os.path.join(REPO, "assets", "style.css.html")).read()

# ------------------------------------------------------------------- the team
# One codebase, more than one team. Everything that used to say "EDW" in the page
# chrome reads from here instead, so pointing the build at another board is a data
# change rather than a find-and-replace. Defaults are EDW's, so an existing
# frozen.json without a TEAM block keeps building exactly as before.
TEAM = {
    "key":    "EDW",
    "name":   "Enterprise Data Warehouse",
    "site":   "EDW Performance Reports",
    "org":    "Wellfit",
    "prefix": "EDW-Sprint ",           # stripped to "S<n>" on the chart axes
    "eyebrow": "Enterprise Data Warehouse \u00b7 Flow &amp; Sprint Metrics",
    "dashboard": "https://wellfit.atlassian.net/jira/dashboards/11272",
    "dashboard_label": "EDW ScrumBan Dashboard",
}
TEAM.update(DATA.get("TEAM") or {})
TKEY, TSITE = TEAM["key"], TEAM["site"]


def _fill(head):
    """The index head is a template shared by every page built on it."""
    return (head.replace("__SITE__", TSITE)
                .replace("__TEAMNAME__", TEAM["name"])
                .replace("__ORG__", TEAM["org"]))


def doclink(key, label):
    """Link to a team guide, when the team has written that guide. A team that has
    not gets no link -- the same rule as the dashboard: a document belongs to the
    team that wrote it, and pointing a second team at the first one's guide is how
    one team ends up reading another team's definitions as its own."""
    url = (GUIDES.get(key) or "").strip()
    return (f'<a class="doclink" href="{url}" target="_blank">{label}</a>'
            if url else "")


def rlink(key, icon, label):
    """Same rule, for the Resources list at the foot of a report."""
    url = (GUIDES.get(key) or "").strip()
    return (f'<a class="rlink" href="{url}" target="_blank">'
            f'<span class="ico">{icon}</span> {label}</a>') if url else ""


def _thr_vs_line(cm, cq1, share, open_):
    """The sentence comparing this period's items and points against the reference.
    With no reference it is not written at all: a team's first period has nothing
    to be up or down on, and inventing a baseline of zero would read as infinite
    improvement."""
    di = _vs(cm["items"], cq1["items"], share)
    dp = _vs(cm["pts"], cq1["pts"], share)
    if di is None or dp is None:
        return ("        There is no earlier period to compare this one against yet, "
                "so the figures above stand on their own.")
    up = "" if open_ else "up "
    tail = (" at the same point in the month" if open_
            else " \u2014 the team is larger and the items are smaller")
    return (f"        Items are {up}{di:+.0f}% on {REF1_SHORT} while points are "
            f"{up}{dp:+.0f}%{tail}.")


def _vs(now, ref, share=1.0):
    """Percentage difference against a reference period, or None when there is no
    reference to differ from. A team's first period has nothing behind it, and a
    period whose figures have not been computed yet reads as zero -- in both cases
    the honest output is no comparison, not a number divided by nothing."""
    ref = (ref or 0) * share
    return (100 * (now / ref - 1)) if ref else None


def _pct(v):
    """A percentage, or a dash where there is no figure. Printing None with a
    per-cent sign after it is how 'we could not measure this' turns into text that
    looks like a measurement."""
    return "&mdash;" if v is None else f"{v}%"


def _days(v):
    return "&mdash;" if v is None else f"{v}d"


def _spark_cap(mk):
    """Caption for the little series line. With nothing closed yet there is no
    series to caption."""
    if not MK_DONE:
        return ("Items closed &middot; nothing closed yet, so there is no series to "
                "plot")
    tail = (" &middot; this " + PERIOD_WORD + " is still running and is not plotted"
            if mk not in MK_DONE else "")
    return f"Items closed &middot; {MK_LABS[0]} to {MK_LABS[-1]}{tail}"


def _consistency_line(b, b0):
    """How much throughput moves period to period, as a share of its own level.

    Two things here used to be written by hand: the comparison against the
    baseline band, and the size of the team that band describes. The headcount is
    read from the baseline periods now, and the whole comparison disappears when
    there is no baseline to make it against -- which is every team's first months."""
    if b.get("consistency") is None:
        return ('<div class="line" style="border-color:var(--warning)">'
                '<span class="vs-tag">Consistency</span><br>Not measurable yet: it '
                'needs more than one closed period to see how much throughput moves '
                'between them.</div>')
    tail = ""
    if BASE_KEYS and b0.get("consistency") is not None and b0 is not b:
        ppl = sum(CAP[k][3] for k in BASE_KEYS) / len(BASE_KEYS)
        tail = (f" Earlier in the year, on the {ppl:.0f}-person team, that figure "
                f"was {b0['consistency']:.0f}%.")
    return ('<div class="line" style="border-color:var(--warning)">'
            f'<span class="vs-tag">Consistency {b["consistency"]:.0f}%</span><br>'
            f'Throughput moves <b>{b["move"]:.1f} items</b> from one month to the '
            f'next on average, {b["consistency"]:.0f}% of the level.{tail}</div>')


def _trend_line(tr, now, prev, pplprev, pplnow):
    """The trend readout. Until the series is long enough to have two windows, it
    says that rather than printing a movement it cannot have measured."""
    if tr is None:
        return ('<div class="line" style="border-color:var(--wf-blue)">'
                '<span class="vs-tag">Trend</span><br>Not enough closed periods yet '
                'to measure a trend. It appears once the series has two windows to '
                'compare.</div>')
    return ('<div class="line" style="border-color:var(--wf-blue)">'
            f'<span class="vs-tag">Trend {tr:+.0f}%</span><br>Average of the last '
            f'three months against the three before them: {now:.0f} vs {prev:.0f} '
            f'items. Team went from {pplprev:.1f} to {pplnow:.1f} people over the '
            'same stretch, so read the two together.</div>')


def _per_clause(cm, cq1):
    """The 'once item size and team size are taken out' clause. It only exists when
    both sides have a points-per-person figure to divide -- a team that does not
    estimate, or a reference period with nobody recorded, has no such number, and
    the sentence ends at the item count instead of claiming one."""
    a, b = cm.get("per"), cq1.get("per")
    if not a or not b:
        return "."
    return (f" &mdash; but {100*(a/b-1):+.0f}% once item size and team size are taken "
            "out. Most of the gap is a bigger team closing smaller items.")


def _pcell(now, ref, lower_is_better=False):
    """One comparison cell of the summary table. With no reference figure the cell
    is a flat dash -- the same thing the table already prints where a comparison
    does not apply -- instead of a percentage against nothing."""
    d = _dv(now, ref)
    if d is None:
        return '<td class="flat">&mdash;</td>'
    good = (d <= 0) if lower_is_better else (d > 0)   # equal is not worse
    return f'<td class="{"pos" if good else "neg"}">{d:+.1f}%</td>'


def _dv(now, ref):
    """Delta against a reference figure, or None when the reference is absent.
    Used where the two sides are already in the same unit (days), so the
    comparison is a difference expressed as a percentage of the reference."""
    return (100 * (now - ref) / ref) if ref else None


def _num(v, fmt="{:.2f}", dash="&mdash;"):
    """Format a figure that may legitimately not exist."""
    return dash if v is None else fmt.format(v)


def _plist(names):
    """'A', 'A and B', 'A, B and C' -- so a sentence about the periods with no data
    reads as a sentence however many of them there are."""
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def quarterlink():
    """The published quarter baseline, for the teams that have one. These pages are
    hand-written historical records, so a team without them gets no link rather than
    a link into another team's history -- or, worse, a 404 that looks like a bug in
    its own site."""
    return ('<a class="rlink" href="2026-q2-baseline.html">'
            '<span class="ico">&#128202;</span> Q2 2026 Report</a>'
            if DATA.get("QUARTERS_CLOSED") else "")


def dashlink():
    """The team's Jira dashboards. A team that has set none gets no link at all --
    pointing it at another team's dashboard is the same class of mistake as reading
    another team's capacity page. A team with more than one gets one link each:
    DS, for instance, watches flow on a Kanban board and plans on a Scrum board,
    and collapsing that into a single "the dashboard" would be a lie about how the
    team works. TEAM["dashboards"] is a list of {url, label}; the older single
    dashboard/dashboard_label pair still works and is read as a list of one."""
    ds = list(TEAM.get("dashboards") or [])
    if not ds and (TEAM.get("dashboard") or "").strip():
        ds = [{"url": TEAM["dashboard"], "label": TEAM.get("dashboard_label")}]
    out = []
    for d in ds:
        url = (d.get("url") or "").strip()
        if not url:
            continue
        lab = (d.get("label") or "").strip() or f'{TEAM["key"]} board'
        out.append(f'<a class="rlink" href="{url}" target="_blank">'
                   f'<span class="ico">&#128200;</span> {lab}</a>')
    return "\n    ".join(out)


def short_sprint(n):
    """'EDW-Sprint 14-26' -> 'S14-26'. Any team's prefix, then the generic one."""
    n = str(n)
    for pre in (TEAM["prefix"], "EDW-Sprint ", "DS-Sprint "):
        if pre and n.startswith(pre):
            return "S" + n[len(pre):]
    return n



def _order_sprints(rows, by_month):
    """Chronological order: month by month, in the order each month lists them.
    A sprint not yet assigned to a month (the one running now) goes last."""
    pos, seen = {}, 0
    for mk in sorted(by_month):
        for n in by_month[mk]:
            pos[n] = seen; seen += 1
    return sorted(enumerate(rows), key=lambda t: (pos.get(t[1][0], 10**6), t[0]))

def _ordered(rows, by_month):
    return [r for _, r in _order_sprints(rows, by_month)]


# ---- the month in progress, merged on top of the frozen periods -------------
# Frozen always wins: a period that has been published is never recomputed, so a
# sprint already in frozen.json is left exactly as it was.
CURRENT = None
_cur = os.path.join(REPO, "data", "current.json")
if os.path.exists(_cur):
    CURRENT = json.load(open(_cur))
if CURRENT and CURRENT.get("kind") == "release":
    CURRENT_RELEASE, CURRENT = CURRENT, None      # merged in the release pass below
else:
    CURRENT_RELEASE = None

# What the Scrum Master recorded at planning, from the Confluence capacity page.
# It covers every sprint the page lists, closed ones included, so an old report can
# still show what its sprints were planned with.
_capsrc    = CURRENT_RELEASE or CURRENT or {}
CAPACITY   = _capsrc.get("CAPACITY") or {}
GOALS_PAGE = _capsrc.get("GOALS") or {}
CAP_URL    = _capsrc.get("CAP_URL")
# Working-agreement changes, with the sprint they took effect. A change in practice
# moves the numbers, and without saying so the charts read it as a change in
# performance -- which is exactly backwards when the change was an improvement.
CHANGES    = _capsrc.get("CHANGES") or []
if CURRENT:
    _mk = CURRENT["ym"].split("-")[1]
    # Frozen wins only for a sprint that belongs to a month already closed. A sprint
    # recorded while it was still open is provisional: the fresh reading replaces it.
    _final = {n for ns in SP_BY_MONTH.values() for n in ns} | {r[0] for r in SPRINTS_Q1}
    _fresh = {r[0] for r in CURRENT["SPRINTS"]} - _final
    SPRINTS[:] = [r for r in SPRINTS if r[0] not in _fresh]
    SPRINTS.extend([r for r in CURRENT["SPRINTS"] if r[0] not in _final])
    for _k, _v in (CURRENT.get("GHOST") or {}).items():
        if _k not in _final: GHOST[_k] = _v
    for _src, _dst in ((CURRENT["SPILL"], SPILL), (CURRENT["SPLIT"], SPLIT),
                       (CURRENT["TIS"], TIS)):
        for _k, _v in _src.items():
            if _k not in _final: _dst[_k] = _v
    for _src, _dst in ((CURRENT["CAP"], CAP), (CURRENT["CYC"], CYC)):
        for _k, _v in _src.items():
            if _k not in DATA.get("MONTHS", {}): _dst[_k] = _v
    if _mk not in MONTHS:
        MONTHS[_mk] = CURRENT["month"]
        SP_BY_MONTH[_mk] = CURRENT["month"]["sprints"]
        SPRINTS[:] = _ordered(SPRINTS, SP_BY_MONTH)
        MONTH_LABEL[_mk] = CURRENT["month"]["label"].split()[0]
        _entry = [CURRENT["month"]["short"], CURRENT["month"]["slug"] + ".html"]
        if _entry not in REPORTS:
            _q = next((i for i, r in enumerate(REPORTS) if r[0].startswith("Q")), len(REPORTS))
            REPORTS.insert(_q, _entry)

# the sprint that is open right now, so the tables can tag it "in progress"
LIVE = None
try:
    LIVE = json.load(open(os.path.join(REPO, "data", "live.json")))
    if (LIVE.get("kind") == "active") and LIVE.get("sprint"):
        ACTIVE = LIVE["sprint"]["name"]
except Exception:
    LIVE = None


def OPEN_SPRINT(n):
    """(day, days) when this sprint is the one running right now, else None.
    Everything that must not hand an open sprint a verdict asks this first."""
    if not LIVE or LIVE.get("kind") != "active":
        return None
    sp_ = LIVE.get("sprint") or {}
    if sp_.get("name") != n or not sp_.get("days"):
        return None
    return (sp_.get("day") or 1, sp_["days"])


def _review(slug):
    """amber until a human signs the page off in data/review.json"""
    try:
        r = json.load(open(os.path.join(REPO, "data", "review.json")))
    except Exception:
        r = {}
    e = r.get(slug) or {}
    return e if e.get("status") == "reviewed" else dict(status="pending", **{k: v for k, v in e.items() if k != "status"})


# ---------------------------------------------------------------- data
# Q1 reconciled 2026-09: official filter (resolution = Done, no sub-tasks/epics) gives 120 closed,
# 44/36/40 per month. The 100 (10/45/45) in the Confluence report is not reproducible under any
# filter variant; 100 matches the Cycle Time population (items that entered In Development), not throughput.
# Cycle Time reconstruido del changelog: primera entrada a "In Development" -> resolutiondate,
# dias calendario, solo items cerrados. "nodev" = cerrados que nunca pasaron por In Development.
def _fmt_day(iso):
    """2026-09-27 -> Sep 27."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{MONTH_ABBR[d.month - 1]} {d.day}"
    except Exception:
        return str(iso)


def cyc_status(c):
    return "healthy" if (c["med"] <= 6 and c["avg"] <= 9) else (
           "warning" if (c["med"] <= 7.2 and c["avg"] <= 10.8) else "risk")

# Q2 2026 (abr-jun) recalculado con el filtro oficial, solo items cerrados.
# Q1 se mantiene con las cifras publicadas en Confluence: su detalle mensual esta en revision.


# sprint, start, end, items, itemsDone, committed(initial scope), finalScope, completedSP, scopeChg%, burndown, scopeSeries
# Split of mid-sprint additions: reactive (labeled Unplanned or issuetype Urgent Task) vs plannable.
# Measurable only while the Unplanned label was being applied: sprints 14-26 to 17-26.
def sp(name):
    for r in SPRINTS + SPRINTS_Q1:
        if r[0] == name: return r


# ---- month windows, derived instead of written by hand ---------------------
# The month in progress is deliberately kept OUT of every statistical window:
# half a month of throughput would drag the band and the trend down for no reason.
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
MK_ALL  = sorted(CAP)
MK_OPEN = CURRENT["ym"].split("-")[1] if CURRENT else None
MK_DONE = [k for k in MK_ALL if k != MK_OPEN]
MK_L3, MK_P3 = MK_DONE[-3:], MK_DONE[-6:-3]
# A team whose reporting starts on the release calendar has no frozen monthly
# series at all. The month pass below is then dead code -- the release pass
# overwrites every one of these -- so it has to survive being empty rather than
# die on an index. EDW, which has the months, is unaffected.
MK_LAST = MK_ALL[-1] if MK_ALL else None
BASE_KEYS = [k for k in ("01","02","03","04","05") if k in CAP]
MK_LABS = [MONTH_ABBR[int(k)-1] for k in MK_DONE]

PNORM = {}   # period key -> how many sprints it spans (1 for a month)

def cl(k):
    """Items closed in period k, on the comparable scale: per sprint for a release,
    as-is for a month. 9.06 ran three sprints and the rest two; without this the
    six-week release would look like a spike that never happened."""
    return CAP[k][0] / PNORM.get(k, 1)

def _plabel(k):
    """Readable name for a period key, including the 'may' cycle-time key."""
    return MONTH_LABEL.get(k) or (MONTH_ABBR[int(k)-1] if str(k).isdigit() else str(k).title())

def _sidx(mk):
    """Where this month sits in the historical series - None while it is still running."""
    return MK_DONE.index(mk) if mk in MK_DONE else None

def _cyckey(k):
    return "may" if k == "05" else k
CYC_ORDER = [_cyckey(k) for k in MK_DONE if _cyckey(k) in CYC]


# ---------------------------------------------------------------- Q1 sprints (board 11)
# Same reconstruction as the later sprints: day-1 scope from the Sprint-field changelog,
# completion from the status history. Note that a closed sprint only retains what was
# finished in it — incomplete items were moved on — so read completion against the
# day-1 commitment, never against final scope.

# ---------------------------------------------------------------- capacity data
# items closed, items carrying story points, story points, active contributors
# (people with >= 2 closed items that month). Basis: resolution = Done, no sub-tasks/epics.

def cap(keys):
    """Averages over the given periods, on the comparable scale (see cl).

    Two of these are ratios and both have a real zero denominator: a team that
    does not estimate closes items with no story points on them, and a period
    with nobody recorded as active has no per-person figure. Those come back as
    None -- the caller decides what to print -- instead of ending the build."""
    n=len(keys) or 1
    nz=lambda k: PNORM.get(k,1)
    it=sum(CAP[k][0]/nz(k) for k in keys); sp=sum(CAP[k][1]/nz(k) for k in keys)
    pt=sum(CAP[k][2]/nz(k) for k in keys); pe=sum(CAP[k][3] for k in keys)/n
    return dict(items=it/n, pts=pt/n, size=(pt/sp if sp else None), people=pe,
                per=((pt/n)/pe if pe else None))

def band(vals):
    """Expected range from the series' own month-to-month movement (XmR).

    A series of one period has no movement to measure, and a mean of zero has no
    percentage to express consistency against. Both are real states for a team
    whose series is just starting, so they come back as a band with no width
    rather than as a crash."""
    mr=[abs(vals[i]-vals[i-1]) for i in range(1,len(vals))]
    mrbar=sum(mr)/len(mr) if mr else 0.0
    mean=sum(vals)/len(vals) if vals else 0.0
    half=2.66*mrbar
    return dict(lo=max(0,mean-half), hi=mean+half, mean=mean, move=mrbar,
                consistency=(100*mrbar/mean) if mean else None)

def trend(keys_now, keys_prev):
    """Movement between two windows of the series. A series too short to have a
    window behind it has no trend yet -- that comes back as None, not as a
    percentage against an empty half."""
    if not keys_now or not keys_prev:
        return None
    a=sum(cl(k) for k in keys_now)/len(keys_now)
    b=sum(cl(k) for k in keys_prev)/len(keys_prev)
    return (100*(a/b-1)) if b else None

# Jira sprint report: completed / not completed at close / removed before close.
# items, points for each. "Removed" is where EDW's spillover hides.
def spill(name):
    return SPILL.get(name) or SPILL_Q1.get(name)


RESPCSS = """
 .tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:14px}
 .tscroll table.exec{min-width:660px}
 .statuspill{display:inline-block;max-width:100%;text-align:left}
 .statuspill .dot{display:inline-block;vertical-align:middle;margin-right:9px}
 @media(max-width:760px){
  .tabs .wrap{overflow-x:auto;white-space:nowrap;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  .tabs .wrap::-webkit-scrollbar{display:none}
  .tab{padding:15px 14px;font-size:14px}
  header{padding:32px 0 28px}
  header h1{font-size:27px}
  .statuspill{font-size:13px;line-height:1.35;padding:9px 14px}
  .bignum{font-size:34px}
  .sectit{font-size:20px}
  .insightbox{padding:20px}
  .insightbox h2{font-size:20px}
 }
 @media(max-width:430px){ .wrap{padding:0 16px} .rp{padding:5px 10px;font-size:11.5px} }
"""

RESIZEJS = r'''
// A chart built inside a hidden panel measures 0x0 and stays that way until
// something tells it to measure again. Tabs, collapsibles and the modal all hide
// charts, and each one used to need its own resize call -- which is why a section
// could open onto what looked like a chart that failed to load. One observer
// watches every chart box instead, so anything that reveals one is covered,
// including whatever gets added later.
(function(){
  if(typeof Chart==='undefined'||typeof ResizeObserver==='undefined') return;
  var ro=new ResizeObserver(function(entries){
    entries.forEach(function(e){
      var w=e.contentRect.width;
      if(!w) return;                         // still hidden
      var cv=e.target.querySelector('canvas');
      if(!cv) return;
      var ch=Chart.getChart(cv);
      if(ch && Math.abs(ch.width-w)>1) ch.resize();
    });
  });
  document.querySelectorAll('.chartbox').forEach(function(b){ ro.observe(b); });
})();
'''

ZOOMJS = r'''
// --- click a chart to open it full size -------------------------------------
(function(){
  if(typeof Chart==='undefined') return;
  const m=document.createElement('div'); m.className='cmodal';
  m.innerHTML='<div class="cmbox"><div class="cmhead"><h4></h4>'+
              '<button class="cmclose" aria-label="Close">&times;</button></div>'+
              '<div class="cmbody"><canvas id="cmCanvas"></canvas></div></div>';
  document.body.appendChild(m);
  const title=m.querySelector('h4'), body=m.querySelector('.cmbody');
  let big=null;
  function close(){ if(big){big.destroy();big=null;} m.classList.remove('open'); }
  m.addEventListener('click',e=>{ if(e.target===m) close(); });
  m.querySelector('.cmclose').addEventListener('click',close);
  document.addEventListener('keydown',e=>{ if(e.key==='Escape') close(); });
  function labelFor(box){
    const card=box.closest('.cmpcard,.card');
    const h=card&&(card.querySelector('.cmphead h3')||card.querySelector('.gname'));
    return h?h.textContent.trim():'Chart';
  }
  function open(src,box){
    if(big) big.destroy();
    title.textContent=labelFor(box);
    body.innerHTML='<canvas id="cmCanvas"></canvas>';
    const cfg=src.config;
    big=new Chart(body.querySelector('canvas'),{
      type:cfg.type,
      data:JSON.parse(JSON.stringify(cfg.data)),
      options:Object.assign({},cfg.options,{responsive:true,maintainAspectRatio:false,animation:false}),
      plugins:cfg.plugins||[]
    });
    m.classList.add('open');
  }
  document.querySelectorAll('canvas').forEach(cv=>{
    const ch=Chart.getChart(cv); if(!ch) return;
    const box=cv.closest('.chartbox')||cv.parentElement;
    if(!box||box.classList.contains('zoomable')) return;
    box.classList.add('zoomable');
    box.addEventListener('click',()=>open(ch,box));
  });
})();
'''

TIPCSS = """
 [data-tip]{cursor:help;border-bottom:1px dotted currentColor;text-decoration:none}
 .tipbox{position:fixed;z-index:300;max-width:320px;background:#12232f;color:#fff;font-size:12.5px;
   line-height:1.5;padding:10px 13px;border-radius:10px;box-shadow:0 8px 26px rgba(0,0,0,.28);
   pointer-events:none;opacity:0;transition:opacity .12s;font-weight:400;letter-spacing:0;text-transform:none}
 .tipbox.on{opacity:1}
"""

TIPJS = r'''
// --- hover tooltips ---------------------------------------------------------
(function(){
  const tip=document.createElement('div'); tip.className='tipbox'; document.body.appendChild(tip);
  let cur=null;
  function show(el){
    cur=el; tip.textContent=el.getAttribute('data-tip'); tip.classList.add('on');
    const r=el.getBoundingClientRect(); tip.style.left='0px'; tip.style.top='0px';
    const t=tip.getBoundingClientRect();
    let x=r.left+r.width/2-t.width/2;
    x=Math.max(10,Math.min(x,window.innerWidth-t.width-10));
    let y=r.top-t.height-9;
    if(y<8) y=r.bottom+9;
    tip.style.left=x+'px'; tip.style.top=y+'px';
  }
  function hide(){ cur=null; tip.classList.remove('on'); }
  document.addEventListener('mouseover',e=>{ const el=e.target.closest('[data-tip]'); if(el&&el!==cur) show(el); });
  document.addEventListener('mouseout',e=>{ const el=e.target.closest('[data-tip]'); if(el&&el===cur) hide(); });
  document.addEventListener('focusin',e=>{ const el=e.target.closest('[data-tip]'); if(el) show(el); });
  document.addEventListener('focusout',hide);
  window.addEventListener('scroll',()=>{ if(cur) show(cur); },{passive:true});
})();
'''

ZOOMCSS = """
 .sprinthead{align-items:center;gap:12px;justify-content:flex-start;margin-bottom:16px}
 .sprinthead h3{flex:0 0 auto}
 .sprintdates{margin-left:auto;font-size:13.5px;color:var(--wf-muted);font-weight:600;white-space:nowrap}
 .badge-lg{font-size:12.5px;padding:5px 13px;letter-spacing:.01em}
 .badge-lg .d{width:8px;height:8px}
 @media(max-width:640px){.sprintdates{margin-left:0;width:100%;white-space:normal}}

 .chartbox.zoomable{position:relative;cursor:zoom-in;border-radius:10px;transition:background .15s}
 .chartbox.zoomable:hover{background:var(--card2)}
 .chartbox.zoomable::after{content:"Expand";position:absolute;top:6px;right:8px;font-size:10.5px;font-weight:700;
   letter-spacing:.08em;text-transform:uppercase;color:var(--wf-blue);background:var(--card);border:1px solid var(--line);
   border-radius:999px;padding:3px 9px;opacity:0;transition:opacity .15s;pointer-events:none}
 .chartbox.zoomable:hover::after{opacity:1}
 .cmodal{position:fixed;inset:0;z-index:200;background:rgba(20,32,44,.68);display:none;
   align-items:center;justify-content:center;padding:28px}
 .cmodal.open{display:flex}
 .cmbox{background:var(--card);border-radius:18px;width:min(1180px,100%);height:min(78vh,760px);
   display:flex;flex-direction:column;box-shadow:0 18px 60px rgba(0,0,0,.35);overflow:hidden}
 .cmhead{display:flex;align-items:center;gap:14px;padding:16px 20px;border-bottom:1px solid var(--line)}
 .cmhead h4{font-size:17px;font-weight:700;color:var(--wf-blue-d);flex:1;line-height:1.3}
 .cmclose{appearance:none;border:1px solid var(--line);background:var(--card);border-radius:9px;width:34px;height:34px;
   font-size:19px;line-height:1;color:var(--wf-muted);cursor:pointer;flex-shrink:0}
 .cmclose:hover{background:var(--card3);color:var(--wf-ink)}
 .cmbody{flex:1;padding:18px 20px 22px;min-height:0}
 @media(max-width:760px){.cmodal{padding:12px}.cmbox{height:min(88vh,620px)}.chartbox.zoomable::after{display:none}}
"""

NAVCSS = """
 .crumb{font-size:12.5px;color:var(--hdr-sub);margin-bottom:12px}
 .crumb a{color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.35)}
 .crumb a:hover{border-color:#fff}
 .repnav{background:var(--card);border-bottom:1px solid var(--line)}
 .repnav .wrap{display:flex;align-items:center;gap:8px;padding-top:11px;padding-bottom:11px;flex-wrap:wrap}
 .repnav .ry{font-size:11px;font-weight:800;letter-spacing:.14em;color:var(--wf-muted);margin-right:2px}
 .rp{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.06em;padding:5px 13px;border-radius:999px;
     text-decoration:none;color:var(--wf-blue-d);background:var(--wf-blue-bg);transition:.15s}
 .rp:hover{background:var(--wf-blue-l);color:#fff}
 .rp.on{background:var(--wf-blue-d);color:#fff;cursor:default}
 .rsep{width:1px;height:18px;background:var(--line);margin:0 5px}
 .rp.live{background:var(--wf-blue);color:#fff;display:inline-flex;align-items:center;gap:7px}
 .rp.live i{width:6px;height:6px;border-radius:50%;background:var(--card);display:block;flex:0 0 auto}
 .rp.live:hover{background:var(--wf-blue-d);color:#fff}
 .rp.live.on{background:var(--wf-blue-d);cursor:default}
 /* These were a 12.5px bare link pushed to the edge. They are the way off the
    page, so they are sized like the pills they sit next to. */
 .rgroup{margin-left:auto;display:flex;align-items:center;gap:8px;flex:0 0 auto}
 .rutil{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:700;
   padding:6px 14px;border-radius:999px;text-decoration:none;color:var(--wf-blue-d);
   background:var(--card);border:1px solid var(--line);white-space:nowrap;transition:.15s}
 .rutil:hover{border-color:var(--wf-blue-l);background:var(--wf-blue-bg)}
 .rutil.on{background:var(--wf-blue-d);border-color:var(--wf-blue-d);color:#fff;cursor:default}
 /* With the active sprint in it the strip no longer fits a phone. It scrolls
    sideways rather than wrapping into three lines. */
 @media(max-width:700px){
  .repnav .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;flex-wrap:nowrap}
  .repnav .wrap::-webkit-scrollbar{display:none}
  .rp,.ry{flex:0 0 auto}
  .rgroup{margin-left:12px;padding-top:0}
 }
"""

def repnav(current, root=False):
    """The strip that moves you between periods.

    The active sprint is in it. It used to be reachable only from one small link on
    the index, and a chip click from the sprint page was a one-way door: the strip
    took you to a report that had no way back. A page that is in the strip can
    always be returned to, which is the whole point of having one.

    `root` is for the pages that sit at the top of the site rather than in 2026/.
    """
    up   = "" if root else "../"
    into = "2026/" if root else ""
    live = ('<span class="rp live on"><i></i>Active sprint</span>' if current == "live"
            else f'<a class="rp live" href="{up}sprint.html"><i></i>Active sprint</a>')
    out = [live, '<span class="rsep"></span>']
    for code, href in REPORTS:
        if code == "Q1":
            out.append('<span class="rsep"></span>')
        if code == current:
            out.append(f'<span class="rp on">{code}</span>')
        else:
            out.append(f'<a class="rp" href="{into}{href}">{code}</a>')
    # The fix-list is not in here. It is not a period, and it is not for the people
    # reading a release report -- the page itself says it is kept away from them.
    # It lives on the two pages whoever maintains the board actually uses, carrying
    # its count, which a nav pill could never do.
    return ('<div class="repnav"><div class="wrap">'
            + "".join(out)
            + '<span class="rgroup">'
            + f'<a class="rutil" href="{up}index.html">&larr; All reports</a>'
            + '</span></div></div>')



# What the stripe on a findings card means. It was never written down anywhere, so
# the colours were decoration: a reader had no way to tell "someone must do this"
# from "worth a conversation". Rank is also the order they are shown in -- the
# cards used to lead with the discussion items and bury the actions underneath.
FIND_RANK = [
    ("p-red",   "Risk",    "needs a decision now"),
    ("p-amber", "Action",  "someone has to do something"),
    ("p-blue",  "Discuss", "bring it to the team; no owner yet"),
    ("p-green", "Cleared", "was true earlier in the series, is not any more"),
    ("p-grey",  "Context", "background for the numbers above"),
]


def _act_blocks(html, start):
    """Every findings card from `start`, with its span, by matching div depth.
    Regex cannot do this: the cards nest three levels deep."""
    out, i = [], start
    while True:
        a = html.find('<div class="act">', i)
        if a < 0:
            break
        j, depth = a, 0
        while j < len(html):
            nxt_o = html.find("<div", j)
            nxt_c = html.find("</div>", j)
            if nxt_c < 0:
                return out
            if nxt_o != -1 and nxt_o < nxt_c:
                depth += 1; j = nxt_o + 4
            else:
                depth -= 1; j = nxt_c + 6
                if depth == 0:
                    break
        out.append((a, j))
        i = j
        if html[j:j+400].find('<div class="act">') < 0:
            break          # end of this run of cards
    return out


def order_findings(html):
    """Put the cards that need doing first, and say what the colours mean.

    Done after the page is built rather than at each of the twelve places a card is
    written, so every page gets the same treatment and a new card cannot be added in
    the wrong order by accident.
    """
    rank = {c: i for i, (c, _, _) in enumerate(FIND_RANK)}
    out, pos = [], 0
    while True:
        runs = _act_blocks(html, pos)
        if len(runs) < 2:
            out.append(html[pos:]); break
        first, last = runs[0][0], runs[-1][1]
        cards = [html[a:b] for a, b in runs]
        keyed = sorted(enumerate(cards),
                       key=lambda t: (next((rank[c] for c in rank if c in t[1][:120]), 9), t[0]))
        used = [c for c in rank if any(c in x[:120] for x in cards)]
        legend = ('<div class="findkey">' +
                  "".join(f'<span><i class="fk {c}"></i><b>{lab}</b> &mdash; {why}</span>'
                          for c, lab, why in FIND_RANK if c in used) +
                  '</div>')
        out.append(html[pos:first] + legend + "".join(c for _, c in keyed))
        pos = last
    return "".join(out)


def add_tips2(html):
    return order_findings(_add_tips(html))


def _add_tips(html):
    import re as _re
    for frag, tip in TIPS.items():
        if frag not in html: continue
        m = _re.match(r'<(th|td|div|span)([^>]*)>(.*)</\1>$', frag, _re.S)
        if not m: continue
        tag, attrs, inner = m.groups()
        rep = f'<{tag}{attrs}><span data-tip="{tip}">{inner}</span></{tag}>'
        html = html.replace(frag, rep)
    return html

BADGE = {"healthy":("b-green","Healthy","var(--healthy)"),
         "warning":("b-amber","Warning","var(--warning)"),
         "risk":("b-red","Risk","var(--risk)"),
         # a period still running is not healthy, warning or risk: it is unfinished
         "open":("b-grey","In progress","var(--wf-muted)")}

# ---- what a period compares itself against -------------------------------
# Months and quarters compare against the closed calendar quarters. Releases
# compare against their own series, because a release is not a month: 9.06 ran
# six weeks and the rest four, so only a per-sprint figure is comparable.
REF1_LABEL = "Q1 2026"      # column header
REF2_LABEL = "Q2 2026"
REF1_SHORT = "Q1"           # inside "vs Q1"
REF2_SHORT = "Q2"
PERIOD_WORD = "month"       # "This month" / "closed · month"


def pdelta(cur, ref):
    """Percent change against a reference, or None when the reference is zero —
    a period where nobody applied the label is not a 0% baseline to divide by."""
    try:
        return 100*(cur-ref)/ref if ref else None
    except (TypeError, ZeroDivisionError):
        return None

def sb_rows(rows):
    """Uniform delta block: label | value | vs Q1 | vs Q2. rows = [(label, value_str, d1, d2, better_low)]"""
    out = [f'<div class="statblock"><div class="sb sb-head"><span></span><span>This {PERIOD_WORD}</span>'
           f'<span>vs {REF1_SHORT}</span><span>vs {REF2_SHORT}</span></div>']
    for lab, val, d1, d2, low in rows:
        def cell(d):
            if d is None: return '<span class="sd flat">&mdash;</span>'
            good = (d < 0) if low else (d > 0)
            return f'<span class="sd {"pos" if good else "neg"}">{d:+.0f}%</span>'
        out.append(f'<div class="sb"><span class="sk">{lab}</span><span class="sv">{val}</span>{cell(d1)}{cell(d2)}</div>')
    return "".join(out) + '</div>'

def spark(vals, cur_idx, col="#007CBC", low_good=False):
    """12-point sparkline, de-emphasised history with the current period in the accent.

    An empty series draws nothing. A team in its first period has no history to
    de-emphasise, and a flat line at zero would read as a measured result."""
    if not vals:
        return ""
    w, h, pad = 260, 34, 3
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    step = (w - 2*pad) / max(1, n-1)
    pts = [(pad + i*step, pad + (h-2*pad) * (1 - (v-lo)/rng)) for i, v in enumerate(vals)]
    d = " ".join(("M" if i==0 else "L") + f"{x:.1f},{y:.1f}" for i,(x,y) in enumerate(pts))
    dot = ""
    if cur_idx is not None and 0 <= cur_idx < n:
        cx, cy = pts[cur_idx]
        dot = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{col}" style="stroke:var(--card)" stroke-width="2"/>'
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-hidden="true">'
            f'<path d="{d}" fill="none" style="stroke:var(--edge)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'{dot}</svg>')

# ---------------------------------------------------------------- sprint detail sections
import json as _json

def goal_box(name):
    g = SPRINT_GOALS.get(name, "")
    if g:
        return f'<div class="goalbox"><b>Sprint goal.</b> {g}</div>'
    return ('<div class="goalbox"><b>No goal recorded in Jira for this sprint.</b> '
            'Without one there is nothing to measure delivery against beyond the point count, '
            'and no way to say whether the sprint achieved what it set out to do.</div>')

def tis_block(name):
    d = TIS.get(name, {}).get("tis", {})
    parts = [(st, d[st]["med"], d[st]["n"]) for st in FLOW_ST if st in d and d[st]["med"] > 0]
    if not parts:
        return ('<div class="sprintsec"><div class="sk">Time in status</div>'
                '<div class="goalbox">Not enough status history in this sprint to measure it.</div></div>')
    total = sum(p[1] for p in parts)
    bars, keys = "", ""
    for st, med, n in parts:
        pct = 100*med/total
        label = f"{med:.1f}d" if pct > 11 else ""
        bars += f'<span style="width:{pct:.1f}%;background:{STCOL[st]}">{label}</span>'
        keys += f'<span><i class="tisdot" style="background:{STCOL[st]}"></i>{st} <b>{med:.1f}d</b> <i style="font-style:normal;color:var(--muted4)">({n} items)</i></span>'
    slow = max(parts, key=lambda x: x[1])
    note = (f'The queue before development is where items wait longest — a median of {slow[1]:.1f} days in <i>{slow[0]}</i>.'
            if slow[0] == "Ready for Development" else
            f'Longest median sits in <i>{slow[0]}</i> at {slow[1]:.1f} days.')
    return (f'<div class="sprintsec"><div class="sk">Time in status &middot; median per item</div>'
            f'<div class="tisbar">{bars}</div><div class="tiskey">{keys}</div>'
            f'<div class="secsub" style="margin-top:7px">{note}</div></div>')

def tis_period(mk):
    """Time in status for a whole period, pooled from its sprints.

    Only the per-sprint medians survive in frozen history, so the pooled figure is
    a mean of those medians weighted by how many items each sprint measured. It is
    an approximation and the page says so: it is right about where the time goes,
    and should not be quoted to two decimals.
    """
    names = [n for n in SP_BY_MONTH.get(mk, []) if n in TIS]
    if not names:
        return None
    acc = {}
    for n in names:
        for st, v in (TIS[n].get("tis") or {}).items():
            if not v.get("n"):
                continue
            a = acc.setdefault(st, {"num": 0.0, "n": 0})
            a["num"] += v["med"] * v["n"]
            a["n"] += v["n"]
    out = {st: {"med": a["num"] / a["n"], "n": a["n"]} for st, a in acc.items() if a["n"]}
    stalled = sum(TIS[n].get("stalled", 0) for n in names)
    items = sum(TIS[n].get("items", 0) for n in names)
    return {"tis": out, "sprints": names, "stalled": stalled, "items": items}


def tis_flow_block(mk):
    """Where the time goes in this period, as one bar. Cycle Time says how long an
    item took; this says which step it spent that time in, which is the only one of
    the two anybody can act on."""
    d = tis_period(mk)
    if not d:
        return ""
    parts = [(st, d["tis"][st]["med"], d["tis"][st]["n"])
             for st in FLOW_ST if st in d["tis"] and d["tis"][st]["med"] > 0]
    if not parts:
        return ""
    total = sum(p[1] for p in parts)
    bars, keys = "", ""
    for st, med, n in parts:
        pct = 100 * med / total
        bars += ('<span style="width:%.1f%%;background:%s">%s</span>'
                 % (pct, STCOL.get(st, "var(--edge)"), (f"{med:.1f}d" if pct > 11 else "")))
        keys += ('<span><i class="tisdot" style="background:%s"></i>%s <b>%.1fd</b> '
                 '<i style="font-style:normal;color:var(--muted4)">(%d items)</i></span>'
                 % (STCOL.get(st, "var(--edge)"), st, med, n))
    slow = max(parts, key=lambda x: x[1])
    share = 100 * slow[1] / total
    if slow[0] == "Ready for Development":
        read = (f"<b>{share:.0f}% of the time an item spends in the flow is spent waiting to be "
                f"picked up</b>, a median of {slow[1]:.1f} days in <i>Ready for Development</i>. "
                "That is a queue in front of the team, not the team being slow.")
    else:
        read = (f"The longest step is <i>{slow[0]}</i> at a median of {slow[1]:.1f} days, "
                f"{share:.0f}% of the time an item spends in the flow.")
    stall = ""
    if d["stalled"]:
        stall = (f" {d['stalled']} of {d['items']} items sat more than five days in a single "
                 "status somewhere in this period.")
    return f'''
 <div class="cmpcard"><div class="cmphead"><h3>Time in status &mdash; where the time actually goes</h3></div>
  <div class="secsub" style="margin-bottom:10px">Pooled across {len(d["sprints"])} sprint(s) of this {PERIOD_WORD}. Cycle Time says how long an item took; this says which step it spent that time in.</div>
  <div class="tisbar">{bars}</div><div class="tiskey">{keys}</div>
  <div class="secsub" style="margin-top:9px">{read}{stall}</div>
  <div class="infopanel ip-amber">Pooled from each sprint's median, weighted by how many items that sprint measured. It is right about where the time goes; it is not precise to the decimal.</div>
 </div>'''


def tis_trend_card():
    """The same breakdown across the series, so a step getting slower is visible
    before it becomes a cycle-time problem."""
    ks = [k for k in MK_DONE if tis_period(k)]
    if len(ks) < 2:
        return "", ""
    rows = {k: tis_period(k)["tis"] for k in ks}
    labs = json.dumps([MONTH_LABEL.get(k, k) for k in ks])
    ds = []
    for st in FLOW_ST:
        vals = [round(rows[k].get(st, {}).get("med", 0), 2) for k in ks]
        if not any(vals):
            continue
        ds.append("{label:%s,data:%s,backgroundColor:'%s',borderRadius:3}"
                  % (json.dumps(st), json.dumps(vals), STCOL.get(st, "var(--edge)")))
    if not ds:
        return "", ""
    js = f"""
new Chart(document.getElementById('cTis'),{{type:'bar',
 data:{{labels:{labs},datasets:[{','.join(ds)}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{
  x:{{stacked:true,grid:{{display:false}}}},
  y:{{stacked:true,beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Median days per item'}}}}}}}}}});"""
    first, last = ks[0], ks[-1]
    tot = lambda k: sum(rows[k].get(st, {}).get("med", 0) for st in FLOW_ST)
    d0, d1 = tot(first), tot(last)
    move = (f"from {d0:.1f}d to {d1:.1f}d" if abs(d1 - d0) > 0.2 else f"flat at about {d1:.1f}d")
    worst = max(FLOW_ST, key=lambda st: rows[last].get(st, {}).get("med", 0))
    card = f'''
 <div class="cmpcard"><div class="cmphead"><h3>Time in status &mdash; the trend</h3></div>
  <div class="secsub" style="margin-bottom:10px">The same breakdown for every closed {PERIOD_WORD}, stacked. What matters is the shape, not the height: which step is growing.</div>
  <div class="cmpgrid">
   <div class="chartbox" style="height:280px"><canvas id="cTis"></canvas></div>
   <div class="readout">
    <div class="line" style="border-color:var(--wf-blue)"><span class="vs-tag">Total time in the flow</span><br>Moved {move} between {MONTH_LABEL.get(first, first)} and {MONTH_LABEL.get(last, last)}, per item.</div>
    <div class="line" style="border-color:var(--warning)"><span class="vs-tag">Biggest step now</span><br><i>{worst}</i>, at a median of <b>{rows[last].get(worst, {}).get("med", 0):.1f}d</b>. A step that grows while the others hold is the one to look at, whatever the total does.</div>
    <div class="line"><span class="vs-tag">Read it with Cycle Time</span><br>Cycle Time can stay flat while the composition changes underneath. That is the case this chart exists to catch.</div>
   </div>
  </div>
 </div>'''
    return card, js


def stalled_block(name):
    d = TIS.get(name, {})
    st, worst, wst = d.get("stalled", 0), d.get("worst", 0), d.get("worstSt", "")
    if not st:
        return ('<div class="sprintsec"><div class="sk">Stalled items</div>'
                '<div class="goalbox">No item sat more than 5 days in a single status.</div></div>')
    return (f'<div class="sprintsec"><div class="sk">Stalled items</div>'
            f'<div class="goalbox"><b>{st} items</b> spent more than 5 days without moving; the worst sat '
            f'<b>{worst:.1f} days</b> in <i>{wst}</i>. Neither team uses the <i>Flagged</i> field or a '
            f'<i>Blocked</i> status, so this is the closest measurable read on what was stuck.</div></div>')

def dist_block(name):
    d = TIS.get(name, {}).get("dist", {})
    if not d: return ""
    tot = sum(d.values())
    order = sorted(d.items(), key=lambda kv: -kv[1])
    bars, keys = "", ""
    for st, n in order:
        pct = 100*n/tot
        col = STCOL.get(st, "var(--edge)")
        bars += f'<span style="width:{pct:.1f}%;background:{col}">{n if pct>7 else ""}</span>'
        keys += f'<span><i class="tisdot" style="background:{col}"></i>{st} <b>{n}</b></span>'
    return (f'<div class="sprintsec"><div class="sk">Work distribution &middot; {tot} items</div>'
            f'<div class="tisbar">{bars}</div><div class="tiskey">{keys}</div></div>')

def health_block(name):
    row = sp(name)
    if not row: return ""
    _,st,en,items,done,comm,final,comp,chg,burn,scope = row
    sl = spill(name) or dict(open=(0,0), out=(0,0))
    gone = sl["open"][1] + sl["out"][1]
    pct = round(100*comp/comm) if comm else 0
    return (f'<div class="healthrow">'
            f'<div class="hcell"><div class="hk">Work complete</div><div class="hv">{pct}%</div>'
            f'<div class="hn">{comp} of {comm} pts committed</div></div>'
            f'<div class="hcell"><div class="hk">Scope change</div><div class="hv" style="color:var(--warning)">+{chg}%</div>'
            f'<div class="hn">{comm} &rarr; {final} pts</div></div>'
            f'<div class="hcell"><div class="hk">Left the sprint</div><div class="hv" style="color:var(--risk)">{gone}</div>'
            f'<div class="hn">points not finished</div></div>'
            f'<div class="hcell"><div class="hk">Items</div><div class="hv">{done}<span style="font-size:15px;color:var(--wf-muted)">/{items}</span></div>'
            f'<div class="hn">closed inside the sprint</div></div></div>')

def spill_rate(name):
    """Points that left the sprint over every point the sprint ever held."""
    sl = spill(name)
    if not sl: return None
    gone = sl["open"][1] + sl["out"][1]
    allp = sl["done"][1] + gone
    if not allp: return None
    return dict(gone=gone, allp=allp, rate=100*gone/allp,
                open_p=sl["open"][1], out_p=sl["out"][1],
                open_i=sl["open"][0], out_i=sl["out"][0])

def spill_series(names):
    rs = [(n, spill_rate(n)) for n in names]
    rs = [(n, r) for n, r in rs if r]
    tot_g = sum(r["gone"] for _, r in rs); tot_a = sum(r["allp"] for _, r in rs)
    op = sum(r["open_p"] for _, r in rs); ou = sum(r["out_p"] for _, r in rs)
    return dict(rows=rs, rate=100*tot_g/tot_a if tot_a else 0, gone=tot_g, allp=tot_a,
                open_share=100*op/tot_g if tot_g else 0, out_share=100*ou/tot_g if tot_g else 0)

def badge(st):
    c,t,_ = BADGE[st]
    return f'<span class="badge {c}"><span class="d"></span>{t}</span>'

def thr_status(closed):
    dev = (abs(closed - Q1["thr_med"]) / Q1["thr_med"] * 100) if Q1["thr_med"] else 0.0
    return "healthy" if dev <= 15 else ("warning" if dev <= 30 else "risk")

REVCSS = """
 .pillrow{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
 .statuspill{margin-top:0}
 .revchip{display:inline-flex;align-items:center;gap:8px;padding:8px 15px;border-radius:999px;
          font-weight:700;font-size:13.5px;letter-spacing:.01em;line-height:1}
 .revchip .ic{font-size:13px;line-height:1}
 .revchip.pend{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.34);color:var(--wf-blue-bg)}
 .revchip.ok{background:rgba(126,217,181,.20);border:1px solid rgba(126,217,181,.55);color:var(--healthy-bg)}
 .revnote{font-size:12.5px;color:var(--wf-muted);margin:-6px 0 18px}
 @media(max-width:600px){.revchip{font-size:12.5px;padding:7px 12px}}
"""

def review_chip(code):
    """Amber-free, header-safe chip. Pending until a human signs the page off."""
    slug = dict(REPORTS).get(code, "")
    if slug in DATA.get("HISTORICAL", []):
        return ('<span class="revchip" style="background:var(--pillbg);color:#6b7383">'
                '<span class="ic">&#128220;</span> Historical record &middot; '
                'published before the sign-off register</span>')
    r = _review(slug)
    if r.get("status") == "reviewed":
        who = r.get("by", "")
        when = r.get("date", "")
        tail = " · ".join([x for x in (who, when) if x])
        url = r.get("url")
        chip = f'<span class="revchip ok"><span class="ic">&#10003;</span> Signed off{(" · " + tail) if tail else ""}</span>'
        return f'<a href="{url}" style="text-decoration:none" title="Sign-off register in Confluence">{chip}</a>' if url else chip
    # No names. "Pending sign-off" is the state a reader needs; who still owes a
    # signature is between the people in the register, and putting it in a public
    # header turns a process state into a callout.
    url  = r.get("url")
    chip = ('<span class="revchip pend"><span class="ic">&#9679;</span> '
            'Generated from Jira · pending sign-off</span>')
    return f'<a href="{url}" style="text-decoration:none" title="Sign-off register in Confluence">{chip}</a>' if url else chip


THEMEJS = "<script>\n/* Theme switch. The report is one token set; dark is those tokens redefined, so the\n   only thing this does is set an attribute and remember the choice. It follows the\n   operating system until somebody chooses, and then it stops following it -- a person\n   who picked light at 9pm meant it. */\n(function () {\n  var KEY = 'edwTheme';\n  var root = document.documentElement;\n  function stored() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }\n  function sysDark() {\n    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;\n  }\n  function apply(t, save) {\n    root.setAttribute('data-theme', t);\n    if (save) { try { localStorage.setItem(KEY, t); } catch (e) {} }\n    var b = document.getElementById('themebtn');\n    if (b) {\n      b.innerHTML = (t === 'dark' ? '\\u2600\\ufe0e Light' : '\\u263D\\ufe0e Dark');\n      b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');\n    }\n    // charts and hand-drawn SVG read the tokens once, so they are told to redraw\n    if (window.__themeRedraw) { try { window.__themeRedraw(); } catch (e) {} }\n  }\n  apply(stored() || (sysDark() ? 'dark' : 'light'), false);\n  if (window.matchMedia) {\n    var mq = window.matchMedia('(prefers-color-scheme: dark)');\n    var onSys = function (e) { if (!stored()) apply(e.matches ? 'dark' : 'light', false); };\n    if (mq.addEventListener) mq.addEventListener('change', onSys);\n  }\n  document.addEventListener('click', function (e) {\n    var b = e.target.closest && e.target.closest('#themebtn');\n    if (!b) return;\n    apply(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);\n  });\n  // tokens, for anything that draws rather than styles\n  window.__tok = function (name, fallback) {\n    var v = getComputedStyle(root).getPropertyValue(name);\n    return (v && v.trim()) || fallback;\n  };\n})();\n</script>"
PREFBTN = '<div class="prefs"><button class="prefbtn" id="themebtn" type="button">&#9789;&#65038; Dark</button></div>'


def head(title, sub, pill, status, current=None):
    _,_,col = BADGE[status]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TKEY} · {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
{CSS}
<style>
 .statuspill .dot{{background:{col}}}
 .scrumgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-bottom:18px}}
 .sh{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow)}}
 .sh .k{{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--wf-muted);font-weight:700}}
 .sh .v{{font-size:32px;font-weight:800;color:var(--wf-blue-d);line-height:1.1;margin-top:6px}}
 .sh .n{{font-size:12.5px;color:var(--wf-muted);margin-top:4px}}
 .progbar{{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:6px 0 10px}}
 .progbar span{{display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700}}
 .nodata{{background:var(--card3);border:1px dashed var(--edge);border-radius:12px;padding:18px;text-align:center;color:var(--wf-muted)}}
 .nodata .big{{font-size:26px;font-weight:800;color:var(--muted3);display:block;margin-bottom:4px}}
 .fnote{{font-size:12.5px;color:var(--wf-muted);border-left:3px solid var(--warning);padding-left:12px;margin-top:14px}}
{NAVCSS}{RESPCSS}{ZOOMCSS}{TIPCSS}{REVCSS}
</style></head>
<body>
{THEMEJS}
<header><div class="wrap">{PREFBTN}<div class="crumb"><a href="../index.html">{TSITE}</a> &rsaquo; {title}</div><div class="eyebrow">{TEAM["eyebrow"]}</div>
<h1>{title}</h1><div class="sub">{sub}</div>
<div class="pillrow" style="margin-top:18px"><div class="statuspill"><span class="dot"></span> {pill}</div>{review_chip(current)}</div></div></header>
<div class="tabs"><div class="wrap">
 <button class="tab active" data-tab="dash">Flow</button>
 <button class="tab" data-tab="scrum">Sprints</button>
 <button class="tab" data-tab="cmp">Comparatives</button>
 <button class="tab" data-tab="act">Findings &amp; Retro</button>
</div></div>
{repnav(current)}
<main><div class="wrap">"""

FOOT = """</div></main>
<footer>__SITE__ · __TEAMNAME__ · __ORG__</footer>
<script>
function showTab(id,scroll){
 const tab=document.querySelector(`.tab[data-tab="${id}"]`), panel=document.getElementById(id);
 if(!tab||!panel)return false;
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
 tab.classList.add('active');panel.classList.add('active');
 try{history.replaceState(null,'','#t='+id);}catch(e){}
 if(window.Chart)panel.querySelectorAll('canvas').forEach(c=>{const ch=Chart.getChart(c);if(ch)ch.resize();});
 if(scroll)window.scrollTo({top:0,behavior:'smooth'});
 return true;}
document.querySelectorAll('.tab').forEach(t=>{t.addEventListener('click',()=>showTab(t.dataset.tab,true));});
document.querySelectorAll('[data-goto]').forEach(l=>{l.addEventListener('click',e=>{
 e.preventDefault();showTab(l.dataset.goto,true);});});
// carry the open tab across reports: the month/quarter pills keep you where you were
function currentTab(){const a=document.querySelector('.tab.active');return a?a.dataset.tab:'';}
document.querySelectorAll('.repnav a.rp:not(.live)').forEach(a=>{a.addEventListener('click',e=>{
 const t=currentTab(); if(t){e.preventDefault();location.href=a.getAttribute('href')+'#t='+t;}});});
(function(){var h=(location.hash||'').replace(/^#/,'').replace(/^t=/,'');if(h&&!showTab(h,false)){var f=document.querySelector('.tab');if(f)showTab(f.dataset.tab,false);}window.scrollTo(0,0);})();
Chart.defaults.font.family="'DM Sans', sans-serif";Chart.defaults.font.size=11;
Chart.defaults.color=__tok('--wf-muted','var(--wf-muted)');
Chart.defaults.maintainAspectRatio=false;
const BLUE='#007CBC',BLUED='#005f91',BLUEL='#65B2D5',GREEN='#4FA800',AMBER='#ED7D31',RED='#d64550',GREY='#c3cdda';
let gridc=__tok('--grid','var(--grid)');
/* A chart is drawn once with the colours it read. When the theme changes it has to
   read them again, so every instance is re-tinted and redrawn in place rather than
   rebuilt -- rebuilding would lose the zoom state and the tooltips. */
window.__themeRedraw=function(){
  if(!window.Chart||!Chart.instances)return;
  const mut=__tok('--wf-muted','var(--wf-muted)'), grd=__tok('--grid','var(--grid)');
  Chart.defaults.color=mut; gridc=grd;
  Object.values(Chart.instances).forEach(c=>{
    const sc=(c.options&&c.options.scales)||{};
    Object.values(sc).forEach(a=>{
      if(a&&a.grid&&a.grid.color)a.grid.color=grd;
      if(a&&a.ticks)a.ticks.color=mut;
      if(a&&a.title)a.title.color=mut;
    });
    if(c.options&&c.options.plugins&&c.options.plugins.legend&&c.options.plugins.legend.labels)
      c.options.plugins.legend.labels.color=mut;
    c.update('none');
  });
};
__CHARTS__
/* Sprints tab: newest first, collapsible cards */
(function(){
 var panel=document.getElementById('scrum'); if(!panel)return;
 var cards=[].slice.call(panel.querySelectorAll('.cmpcard')).filter(function(c){return c.querySelector('.sprinthead');});
 if(!cards.length)return;
 var active=panel.querySelector('.activewrap .cmpcard');
 var order=cards.filter(function(c){return c!==active;});

 var groups=[],seen=[];
 order.forEach(function(c){
  var h=c.previousElementSibling,key=null;
  while(h){ if(h.classList&&h.classList.contains('sectit')){key=h;break;} h=h.previousElementSibling; }
  var i=seen.indexOf(key); if(i<0){seen.push(key);groups.push([]);i=groups.length-1;}
  groups[i].push(c);
 });
 groups.forEach(function(g){
  if(g.length<2)return;
  var parent=g[0].parentNode, anchor=g[g.length-1].nextSibling;
  g.slice().reverse().forEach(function(c){parent.insertBefore(c,anchor);});
 });

 cards.forEach(function(c,ix){
  var head=c.querySelector('.sprinthead');
  var body=document.createElement('div'); body.className='spcbody';
  var n=head.nextSibling; while(n){var nx=n.nextSibling; body.appendChild(n); n=nx;}
  c.appendChild(body); c.classList.add('spc');

  var vals=[].slice.call(body.querySelectorAll('.scrumgrid .sh')).map(function(sh){
   var v=sh.querySelector('.v'); return v?v.textContent.trim():'';});
  var dates=head.querySelector('.sprintdates');
  if(vals.length>=4){
   var s=document.createElement('span'); s.className='spcsum';
   s.textContent=vals[0]+' committed → '+vals[2]+' done · '+vals[3]+' of commitment';
   if(dates) head.insertBefore(s,dates); else head.appendChild(s);
  }
  var t=document.createElement('span'); t.className='spctoggle';
  t.innerHTML='<span class="tx">Show details</span><span class="cv">▼</span>';
  head.appendChild(t);

  head.setAttribute('role','button'); head.setAttribute('tabindex','0');
  head.setAttribute('aria-expanded','false');
  function toggle(){
   var open=c.classList.toggle('open');
   head.setAttribute('aria-expanded',open?'true':'false');
   t.querySelector('.tx').textContent=open?'Hide details':'Show details';
   if(open&&window.Chart)body.querySelectorAll('canvas').forEach(function(cv){var ch=Chart.getChart(cv);if(ch)ch.resize();});
  }
  head.addEventListener('click',toggle);
  head.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();}});
 });

 var first=panel.querySelector('.activewrap .cmpcard.spc') || panel.querySelector('.cmpcard.spc');
 if(first){var h=first.querySelector('.sprinthead'); if(h)h.click();}

 panel.querySelectorAll('table.exec tbody').forEach(function(tb){
  var rows=[].slice.call(tb.children);
  if(rows.length>1)rows.reverse().forEach(function(r){tb.appendChild(r);});
 });
})();

{ZOOMJS}
</script></body></html>"""

def changes_for(topic):
    """Practice changes that touch this metric."""
    t = topic.lower()
    return [c for c in CHANGES if not c.get("affects") or any(t in a for a in c["affects"])]


def change_note(topic):
    """The panel that stops an improvement from reading as a decline."""
    cs = changes_for(topic)
    if not cs:
        return ""
    out = []
    for c in cs:
        when = f' on {c["date"]}' if c.get("date") else ""
        eff = f' {c["effect"]}' if c.get("effect") else ""
        out.append('<div class="infopanel ip-amber"><b>The team changed how it works at '
                   f'{c["sprint"]}{when}.</b> {c["what"]}{eff} '
                   f'<a href="{CAP_URL}" style="color:inherit">Practice changes &rarr;</a></div>'
                   if CAP_URL else
                   '<div class="infopanel ip-amber"><b>The team changed how it works at '
                   f'{c["sprint"]}{when}.</b> {c["what"]}{eff}</div>')
    return "".join(out)


def change_marks(labels, topic):
    """A Chart.js plugin that draws the change as a line on the series, so the break
    is visible on the chart and not only in the prose beside it."""
    cs = changes_for(topic)
    marks = []
    for c in cs:
        short = short_sprint(c["sprint"])
        if short in labels:
            marks.append({"i": labels.index(short), "t": "practice changed"})
    if not marks:
        return "", ""
    change_marks.n = getattr(change_marks, "n", 0) + 1
    name = f"chg{change_marks.n}"     # one per chart: two charts cannot share a const
    js = (f"const {name}={{id:'{name}',afterDraw(c){{const{{ctx,chartArea:{{top,bottom}},"
          "scales:{x}}=c;" + json.dumps(marks) +
          ".forEach(m=>{const xp=x.getPixelForValue(m.i)-x.width/x.ticks.length/2;"
          "ctx.save();ctx.strokeStyle='#ED7D31';ctx.lineWidth=1.5;ctx.setLineDash([4,3]);"
          "ctx.beginPath();ctx.moveTo(xp,top);ctx.lineTo(xp,bottom);ctx.stroke();ctx.setLineDash([]);"
          "ctx.fillStyle='#ED7D31';ctx.font='700 9.5px DM Sans';ctx.textAlign='left';"
          "ctx.fillText(m.t,xp+4,top+10);ctx.restore();});}};")
    return js, name


def recv_card():
    """Spillover has two ends. The series has always shown only the giving one."""
    rows = [(n, spill(n)) for n in [r[0] for r in SPRINTS]]
    rows = [(n, sl) for n, sl in rows if sl and sl.get("in") is not None]
    if not rows:
        return ""
    got  = sum(sl["in"][1] for _, sl in rows)
    gave = sum(sl["open"][1] + sl["out"][1] for _, sl in rows)
    comm = sum(sp(n)[5] for n, _ in rows if sp(n))
    share = round(100 * got / comm) if comm else 0
    worst = max(rows, key=lambda r: r[1]["in"][1])
    wfrom = worst[1].get("in_from") or "the sprint before"
    net = got - gave
    if abs(net) <= 0.15 * max(got, gave, 1):
        verdict = "takes in about as much as it hands on, which is what a queue looks like"
    elif net < 0:
        verdict = "hands on more than it takes in, so the carry-over is still growing"
    else:
        verdict = "takes in more than it hands on, so it is working the backlog down"
    return (
     '<div class="cmpcard"><div class="cmphead"><h3>Spillover, both ends &mdash; what a sprint '
     'takes in and what it hands on</h3></div>'
     '<div class="secsub" style="margin-bottom:10px">Inherited is work already open in the '
     'previous sprint that arrived inside the day-1 commitment. It is capacity spent before the '
     'sprint began.</div>'
     '<div class="cmpgrid">'
     '<div class="chartbox" style="height:280px"><canvas id="cRecv"></canvas></div>'
     '<div class="readout">'
     '<div class="line" style="border-color:var(--wf-blue)"><span class="vs-tag">'
     + str(share) + '% of everything committed was inherited</span><br><b>' + str(got) + ' of '
     + str(comm) + ' points</b> across the series were already open when the sprint started. '
     'Planning that treats the whole commitment as new work is planning with room the team '
     'does not have.</div>'
     '<div class="line" style="border-color:var(--warning)"><span class="vs-tag">'
     + str(got) + ' in, ' + str(gave) + ' out</span><br>Over the series the team ' + verdict + '.</div>'
     '<div class="line" style="border-color:var(--risk)"><span class="vs-tag">Heaviest: '
     + worst[0] + '</span><br>Started with <b>' + str(worst[1]["in"][1]) + ' points</b> already '
     'open, inherited from ' + wfrom + '.</div>'
     '</div></div>'
     + change_note("spillover") +
     '<div class="infopanel ip-amber">Inherited work is counted at day 1 only. Something pulled '
     'in mid-sprint from an older sprint is scope change, not inheritance, and shows in the '
     'Added column instead.</div></div>')


def recv_line(n, comm):
    """What the sprint inherited. A sprint that starts a third full has a third less
    room than its capacity suggests, and until now the reports only showed the giving
    end of that transfer."""
    sl = spill(n) or {}
    got = sl.get("in")
    if not got or not got[0]:
        return ""
    items, pts = got[0], got[1]
    pct = sl.get("in_pct")
    if pct is None and comm:
        pct = round(100 * pts / comm)
    frm = sl.get("in_from")
    style = ' style="color:var(--warning)"' if (pct or 0) >= 30 else ''
    pcttxt = f" &middot; {pct}% of the day-1 commitment" if pct is not None else ""
    src = frm or "the previous sprint"
    return ('<div class="spill"><div class="sk">Inherited from the sprint before</div>'
            f'<div class="sv"{style}>{pts} pts'
            '<span style="font-size:14px;color:var(--wf-muted);font-weight:600">'
            f' &middot; {items} items{pcttxt}</span></div>'
            f'<div class="sn">Work that was already open in <b>{src}</b> and came in with the '
            'commitment. It is capacity that was spent before the sprint started.</div></div>')


def cap_line(n):
    """What this sprint was planned with, from the capacity page. Planned capacity
    and delivered points are different questions, so this sits beside the burndown
    rather than being folded into it."""
    c = CAPACITY.get(n)
    g = GOALS_PAGE.get(n) or {}
    if not c and not g:
        return ""
    bits = []
    if c:
        if c.get("members"):  bits.append(f"<b>{int(c['members'])}</b> people")
        if c.get("pct") is not None: bits.append(f"capacity <b>{int(c['pct'])}%</b>")
        if c.get("eff_days"): bits.append(f"{int(c['eff_days'])} effective days")
        if c.get("pto"):      bits.append(f"{int(c['pto'])}d PTO")
        if c.get("holidays"): bits.append(f"{int(c['holidays'])} holiday" + ("s" if c["holidays"] > 1 else ""))
    tail = ""
    if g.get("committed") is not None:
        _,_,_,_,_,comm,_,_,_,_,_ = sp(n)
        tail = (f" Planning recorded <b>{int(g['committed'])} pts</b> committed; Jira reconstructs "
                f"<b>{comm}</b>." + (" The gap is what moved after planning."
                                     if int(g["committed"]) != comm else ""))
    src = f' <a href="{CAP_URL}" style="color:var(--wf-muted)">capacity page &rarr;</a>' if CAP_URL else ""
    return ('<div class="spill"><div class="sk">Planned capacity</div>'
            f'<div class="sn" style="margin-top:2px">{" &middot; ".join(bits) if bits else "Not recorded for this sprint."}'
            f'{tail}{src}</div></div>')


def sprint_card(name, idx, note=""):
    n,st,en,items,done,comm,final,comp,chg,burn,scope = sp(name)
    pct = round(100*comp/comm) if comm else 0
    open_sp = final - comp
    sl = spill(n) or dict(done=(0,0), open=(0,0), out=(0,0))
    gone_i = sl["open"][0] + sl["out"][0]
    gone_p = sl["open"][1] + sl["out"][1]
    run = OPEN_SPRINT(n)
    cap_html = cap_line(n)
    recv_html = recv_line(n, comm)
    if run:
        # mid-sprint there is no spillover and no result: open work is just open
        spill_html = ('<div class="spill"><div class="sk">Still open</div>'
                      f'<div class="sv">{gone_p} pts<span style="font-size:14px;color:var(--wf-muted);font-weight:600"> &middot; {gone_i} items</span></div>'
                      f'<div class="sn">Work in flight on day {run[0]} of {run[1]}. Whatever is still open '
                      f'on {en} becomes the spillover into the next sprint — not before.</div></div>')
    elif gone_p:
        bits = []
        if sl["out"][0]:  bits.append(f"{sl['out'][0]} removed before the sprint closed")
        if sl["open"][0]: bits.append(f"{sl['open'][0]} still open at close")
        sr = spill_rate(n)
        spill_html = (f'<div class="spill"><div class="sk">Spillover</div>'
                      f'<div class="sv">{sr["rate"]:.0f}%<span style="font-size:14px;color:var(--wf-muted);font-weight:600"> &middot; {gone_p} of {sr["allp"]} pts</span></div>'
                      f'<div class="sn">{gone_i} items — {" · ".join(bits)}. '
                      f'{"The dotted line on the burndown is where the sprint would have stood if none of it had been taken out." if GHOST.get(n) else "The burndown drops when this work leaves the sprint, not only when it is finished."}</div></div>')
    else:
        spill_html = ('<div class="spill"><div class="sk">Left the sprint</div>'
                      '<div class="sv" style="color:var(--healthy)">0 pts</div>'
                      '<div class="sn">Nothing removed and nothing left open at close.</div></div>')
    return f"""
 <div class="cmpcard">
   <div class="cmphead sprinthead">
     <h3>{n}</h3>
     <span class="badge badge-lg {'b-amber' if chg>=50 else 'b-green'}"><span class="d"></span>scope +{chg}%</span>
     <span class="sprintdates">{st} &rarr; {en}</span>
   </div>
   <div class="scrumgrid">
     <div class="sh"><div class="k">Committed at start</div><div class="v">{comm}</div><div class="n">story points in scope on day 1</div></div>
     <div class="sh"><div class="k">Added during sprint</div><div class="v">+{final-comm}</div><div class="n">final scope {final} points</div></div>
     <div class="sh"><div class="k">Completed</div><div class="v">{comp}</div><div class="n">{done} of {items} items{' · still open ' + str(open_sp) + ' pts' if open_sp else ''}</div></div>
     {f'<div class="sh"><div class="k">Sprint elapsed</div><div class="v">Day {run[0]}</div><div class="n">of {run[1]} — no verdict until it closes</div></div>' if run else f'<div class="sh"><div class="k">vs commitment</div><div class="v">{pct}%</div><div class="n">completed against day-1 scope</div></div>'}
   </div>
   <div class="chartbox" style="height:310px"><canvas id="bd{idx}"></canvas></div>
   {cap_html}
   {recv_html}
   {spill_html}
   {goal_box(n)}
   {tis_block(n)}
   {stalled_block(n)}
   {note}
 </div>"""

def month_scrum_insight(mk):
    # the sprint still running has not "left points unfinished" — it is unfinished
    names = [n for n in SP_BY_MONTH[mk] if sp(n) and not OPEN_SPRINT(n)]
    if not names:
        return ""
    gone_p = sum((spill(n) or dict(open=(0,0),out=(0,0)))["open"][1] +
                 (spill(n) or dict(open=(0,0),out=(0,0)))["out"][1] for n in names)
    rows = [sp(n) for n in names]
    chgs = [r[8] for r in rows]
    lo, hi = min(chgs), max(chgs)
    span = f"+{lo}%" if lo == hi else f"+{lo}% to +{hi}%"
    measurable = [n for n in names if SPLIT.get(n)]
    if measurable:
        rs = [SPLIT[n]["react"] for n in measurable]
        ps = [SPLIT[n]["plan"] for n in measurable]
        pct = round(100*sum(rs)/(sum(rs)+sum(ps)))
        tail = (f"Of everything added after day 1, <span class=\"stat\">{pct}%</span> carried a reactive marker "
                f"— labeled <i>Unplanned</i> or typed <i>Urgent Task</i>. The rest came in as ordinary planned work.")
    else:
        tail = ("The <i>Unplanned</i> label was not being applied in these sprints, so the reactive share "
                "cannot be computed — the split shows as no data, not as zero reactive work.")
    return f'''
 <div class="insightbox" style="margin-bottom:24px"><div class="k">Sprints closed in this {PERIOD_WORD}</div>
  <h2>Scope grew {span} after the sprints had started, and {gone_p} points left the sprints without finishing.</h2>
  <p>{tail} The series-wide view — velocity, scope-change trend and the full sprint table — lives in the
  <a href="#" class="ip-link" data-goto="cmp" style="color:#fff;border-bottom:1px solid rgba(255,255,255,.5)">Comparatives tab</a>.</p>
 </div>'''

def sprint_table(names, short=False):
    rows = ""
    for n in names:
        _,st,en,items,done,c0,final,comp_sp,chg,_,_ = sp(n)
        pct = round(100*comp_sp/c0) if c0 else 0
        run = OPEN_SPRINT(n)
        tag = (f' <span class="runtag">day {run[0]} of {run[1]}</span>' if run
               else (' <span style="color:var(--wf-muted)">in progress</span>' if n == ACTIVE else ""))
        sl = SPLIT.get(n, SPLIT_Q1.get(n))
        cells = (f'<td>{sl["react"]}</td><td class="neg">{sl["plan"]}</td><td>{sl["pct"]}%</td>' if sl
                 else '<td class="flat">no data</td><td class="flat">no data</td><td class="flat">—</td>')
        sl2 = spill(n) or dict(open=(0,0), out=(0,0))
        gp = sl2["open"][1] + sl2["out"][1]
        gcell = (f'<td class="neg">{gp}</td>' if gp else '<td>0</td>')
        # a sprint that has not closed cannot be measured against its commitment:
        # 14% on day 2 is a position, not a result, and reads as a failure in a table
        vcell = '<td class="flat">still running</td>' if run else f'<td>{pct}%</td>'
        if run:
            gcell = '<td class="flat">&mdash;</td>'
        rowcls = ' class="runrow"' if run else ''
        rows += (f'<tr{rowcls}><td>{n}{tag}</td><td>{st} - {en}</td><td>{c0}</td><td>+{final-c0}</td>'
                 f'<td>{comp_sp}</td>{gcell}{vcell}{cells}</tr>')
    return f'''<div class="tscroll"><table class="exec">
  <thead><tr><th>Sprint</th><th>Dates</th><th>Committed</th><th>Added</th><th>Completed</th><th>Left sprint</th><th>vs commit</th><th>Added: reactive</th><th>Added: plannable</th><th>% reactive</th></tr></thead>
  <tbody>{rows}</tbody>
 </table></div>'''

def scrum_tab(mk=None, names=None, title="Sprint metrics", sub="Every sprint of the series, rebuilt from Jira.", intro=""):
    """Monthly page: only this month's sprints. Quarter page: the whole series."""
    if mk and mk in SP_BY_MONTH:
        # a period can name a sprint that has not run yet, or one whose data has
        # not been collected; render what exists rather than failing the page
        names = [n for n in SP_BY_MONTH[mk] if sp(n)]
        missing = [n for n in SP_BY_MONTH[mk] if not sp(n)]
        # A sprint that is still running belongs to the period but not to its
        # result. Leaving it in made day 2 of Sprint 22-26 read as "14% vs
        # commitment" under a heading that said the sprint had closed.
        running = [n for n in names if OPEN_SPRINT(n)]
        names   = [n for n in names if n not in running]
        # the chart JS emits one canvas per sprint of the FULL period, indexed by
        # position in it. Cards must use that same index or the canvas and the
        # chart drift apart and the card renders an empty box.
        CIDX = {n: i for i, n in enumerate([x for x in SP_BY_MONTH[mk] if sp(x)])}
        cards = "".join(sprint_card(n, CIDX[n]) for n in names)
        if not cards:
            cards = ('<div class="goalbox">No sprint of this period has closed yet. '
                     'The numbers on this page are a position, not a result.</div>')
        if missing:
            cards += ('<div class="goalbox" style="margin-top:12px">'
                      + ", ".join(f"<b>{n}</b>" for n in missing)
                      + (" has" if len(missing) == 1 else " have")
                      + " not run yet, so " + ("it is" if len(missing)==1 else "they are")
                      + " not measured here. This period is not complete.</div>")
        extra = ""
        if running:
            _n = running[0]; _d, _dn = OPEN_SPRINT(_n)
            _left = _dn - _d
            extra = ('<div class="activewrap"><span class="activetag">Sprint open right now</span>'
                     f'<div class="secsub" style="margin-bottom:10px"><b>{_n}</b> is on '
                     f'<b>day {_d} of {_dn}</b>, with {_left} day{"" if _left == 1 else "s"} to go. '
                     f'It is shown here because it belongs to {MONTH_LABEL[mk]}, but it is '
                     'not in the totals above and gets no verdict until it closes.</div>'
                     + dist_block(_n) + sprint_card(_n, CIDX[_n]) + '</div>')
        elif mk == MK_LAST and ACTIVE and ACTIVE not in names and sp(ACTIVE):
            live_sp = (LIVE or {}).get("sprint") or {}
            if (LIVE or {}).get("kind") == "active":
                tag, note = "Sprint open right now", (
                    f"Not part of {MONTH_LABEL[mk]} — {ACTIVE} is still running, "
                    f"{live_sp.get('time_elapsed', 0)}% of its calendar elapsed.")
            else:
                tag, note = "Most recent sprint", (
                    f"Not part of {MONTH_LABEL[mk]} — {ACTIVE} closed on "
                    f"{live_sp.get('end', '')}. No sprint is open on this board right now.")
            extra = (f'<div class="activewrap"><span class="activetag">{tag}</span>'
                     f'<div class="secsub" style="margin-bottom:10px">{note}</div>'
                     + health_block(ACTIVE) + dist_block(ACTIVE) + sprint_card(ACTIVE, 90) + '</div>')
            names = names + [ACTIVE]
        names = names + running      # the table shows it, flagged, without a verdict
        return f"""
<section class="panel" id="scrum">
 <div class="sectit">Sprint metrics — {MONTH_LABEL[mk]}</div>
 <div class="secsub">The sprints that closed in this {PERIOD_WORD}, rebuilt from Jira.</div>
 {month_scrum_insight(mk)}
 {extra}
 <div class="sectit" style="font-size:20px;margin-top:28px">Sprints that closed in {MONTH_LABEL[mk]}</div>
 <div class="secsub">Newest first. Grey is total scope, blue is work still open; a healthy sprint has a flat grey line and a falling blue one.</div>
 {cards}
 <div class="sectit" style="font-size:20px;margin-top:28px">Committed vs Completed — {MONTH_LABEL[mk]}</div>
 <div class="secsub">Day-1 commitment against what was added mid-sprint and what actually closed.</div>
 {sprint_table(names)}
</section>"""
    # quarter / fallback: full series
    allnames = names if names else [r[0] for r in SPRINTS]
    cards = "".join(sprint_card(n, i, SPRINT_NOTE_Q1.get(n) and
                    f'<div class="infopanel ip-amber">{SPRINT_NOTE_Q1[n]}</div>' or "")
                    for i, n in enumerate(allnames))
    body = intro if names else series_block(heading=False)
    return f"""
<section class="panel" id="scrum">
 <div class="sectit">{title}</div>
 <div class="secsub">{sub}</div>
 {body}
 <div class="sectit" style="font-size:20px;margin-top:28px">Burndown per sprint</div>
 <div class="secsub">Grey is total scope, blue is work still open.</div>
 {cards}
 {'<div class="sectit" style="font-size:20px;margin-top:28px">Committed vs Completed</div><div class="secsub">Day-1 commitment against what was added mid-sprint and what closed.</div>' + sprint_table(allnames) if names else ''}
</section>"""


def _split_range():
    """The reactive share of mid-sprint additions, over the sprints where the label
    was still being applied. Written by hand once as "8% to 58%"; it is read from the
    data now, because the next team's range is not this team's."""
    v = sorted(x["pct"] for x in SPLIT.values() if x and x.get("pct") is not None)
    if not v:
        return None
    mid = v[len(v)//2] if len(v) % 2 else (v[len(v)//2-1] + v[len(v)//2]) / 2
    return {"lo": v[0], "hi": v[-1], "mid": mid, "n": len(v)}


def _scope_growth():
    """Final scope over day-1 commitment, across every sprint in the series."""
    c = f = 0.0
    for r in SPRINTS:
        c += r[5]; f += r[6]
    return (f / c) if c else None


def _burndown_insight():
    """What the burndowns show, with the numbers read rather than remembered."""
    g, r = _scope_growth(), _split_range()
    if not g:
        return ""
    head = (f"Scope grows <b>{g:.2f}\u00d7</b> between day 1 and the end of a sprint"
            + (f", and most of what arrives is not reactive work."
               if r and r["mid"] < 50 else "." if not r else
               ", and most of what arrives is reactive work."))
    body = (f"A service team cannot plan every request: urgent work lands mid-sprint, "
            f"which is exactly what Planned vs Unplanned exists to measure, so some scope "
            f"growth is expected. The question is how much of it was genuinely "
            f"unplannable. ")
    if r:
        body += (f"Over the <b>{r['n']}</b> sprint{'s' if r['n'] != 1 else ''} where the "
                 f"<i>Unplanned</i> label was still being applied, reactive work accounts for "
                 f"<span class=\"stat\">{r['lo']:.0f}% to {r['hi']:.0f}%</span> of everything "
                 f"added after day 1, with a median of <b>{r['mid']:.0f}%</b>. The rest could "
                 f"have been on the board from the start.")
    else:
        body += ("The <i>Unplanned</i> label is not being applied on any sprint in this "
                 "series, so the split cannot be measured at all.")
    return ('<div class="insightbox" style="margin-bottom:24px">'
            '<div class="k">What the burndowns show</div>'
            f'<h2>{head}</h2><p>{body}</p></div>')

def series_block(heading=True):
    """Historical, series-wide Scrum view. Lives in Comparatives on monthly pages."""
    closed = [r[7] for r in SPRINTS if r[0] != ACTIVE]
    avg5 = round(sum(closed[-5:])/5, 1)
    b  = band([cl(k) for k in MK_L3])
    b0 = band([cl(k) for k in BASE_KEYS]) if BASE_KEYS else b
    ss = spill_series([r[0] for r in SPRINTS])
    tr = trend(MK_L3, MK_P3)
    now  = sum(cl(k) for k in MK_L3)/len(MK_L3) if MK_L3 else 0
    prev = sum(cl(k) for k in MK_P3)/len(MK_P3) if MK_P3 else 0
    pplnow  = sum(CAP[k][3] for k in MK_L3)/len(MK_L3) if MK_L3 else 0
    pplprev = sum(CAP[k][3] for k in MK_P3)/len(MK_P3) if MK_P3 else 0
    head = ('<div class="sectit" style="font-size:20px;margin-top:30px">Sprint series — full history</div>'
            '<div class="secsub">Every sprint of 2026 on the board, so the month can be read against the trend.</div>'
            if heading else "")
    return f"""
 {head}
 <div class="sectit" style="font-size:20px;margin-top:4px">Committed vs Completed — full series</div>
 <div class="secsub">Every sprint on the board this year.</div>
 {sprint_table([r[0] for r in SPRINTS])}
 <div class="fnote">Carry-over between sprints is close to zero, which at first looks like exceptional planning. The added column explains it: little carries over because little is committed up front — the sprint is filled in as it runs. For a service team part of that is unavoidable, but the reactive split shows most of the filling is plannable work. Two separate conversations for the retro: how much service load to reserve capacity for, and why plannable work is not on the board on day 1.</div> <div class="cmpcard">
  <div class="cmphead"><h3>Velocity per sprint</h3></div>
  <div class="secsub" style="margin-bottom:8px">Points completed against the day-1 commitment, and against the documented baseline of {VEL_BASE} (range {VEL_LO}-{VEL_HI}).</div>
  <div class="chartbox" style="height:300px"><canvas id="cVel"></canvas></div>
  <div class="infopanel ip-red">The average of the last 5 closed sprints is <b>{avg5} points</b>, against a baseline of {VEL_BASE}. Same gap Throughput shows: the reference describes the 4-dev team, not this one. But note the commitment bars — the team consistently delivers far more than it commits to, which makes the commitment, not the delivery, the number to fix first.</div>
 </div>

 <div class="cmpcard"><div class="cmphead"><h3>Trend, expected range and consistency</h3></div>
  <div class="secsub" style="margin-bottom:10px">Throughput scales with team size, so a fixed target cannot hold. These three readings do not depend on one.</div>
  <div class="cmpgrid">
   <div class="chartbox" style="height:280px"><canvas id="cBand"></canvas></div>
   <div class="readout">
    {_trend_line(tr, now, prev, pplprev, pplnow)}
    <div class="line" style="border-color:var(--healthy)"><span class="vs-tag">Expected range {b['lo']:.0f} - {b['hi']:.0f}</span><br>Built from the team's own month-to-month movement, not from a target. A month outside it means something changed; a month inside is normal variation.</div>
    {_consistency_line(b, b0)}
   </div>
  </div>
  <div class="infopanel ip-amber">The range re-centres only after a signal has been explained — a team change, a workflow change, or a change in how work arrives. It does not drift quietly along with the numbers.</div>
 </div>
 <div class="cmpcard"><div class="cmphead"><h3>Spillover — what does not finish, and where it goes</h3></div>
  <div class="secsub" style="margin-bottom:10px">Points that left the sprint over every point the sprint ever held. Same source as Jira's own sprint report.</div>
  <div class="cmpgrid">
   <div class="chartbox" style="height:280px"><canvas id="cSpill"></canvas></div>
   <div class="readout">
    <div class="line" style="border-color:var(--risk)"><span class="vs-tag">{ss['rate']:.0f}% of everything committed</span><br><b>{ss['gone']} of {ss['allp']} points</b> across the series did not finish in the sprint they were in. That is a third of the work, every sprint, and it is invisible in the burndown.</div>
    <div class="line" style="border-color:var(--warning)"><span class="vs-tag">{ss['out_share']:.0f}% of it is removed, not carried</span><br>{TKEY} takes work <i>out</i> of the sprint before closing it rather than letting it show as incomplete. That is why every sprint reads 100% complete — the sprint empties before it closes.</div>
    <div class="line" style="border-color:var(--wf-blue)"><span class="vs-tag">Read it against the commitment, not the burndown</span><br>A sprint that commits to 45 points, grows to 117, closes 69 and drops 48 has not delivered 100% of anything. The honest pair is day-1 commitment and spillover rate, side by side.</div>
   </div>
  </div>
  {change_note("spillover")}
  <div class="infopanel ip-amber">There is no sprint goal recorded on any of these sprints, so spillover cannot be read against what the sprint set out to achieve — only against the points. Recording a goal is what would make the difference between "we dropped 48 points" and "we dropped 48 points and still got there".</div>
 </div>
 {recv_card()}
 {_burndown_insight()}
 <div class="cmpcard">
  <div class="cmphead"><h3>Where the mid-sprint work comes from</h3></div>
  <div class="cmpgrid">
   <div class="chartbox" style="height:280px"><canvas id="cSplit"></canvas></div>
   <div class="readout">
    <div class="line" style="border-color:var(--healthy)"><span class="vs-tag">Reactive, as expected</span><br>A handful of points a sprint arrive labeled <i>Unplanned</i> or as <i>Urgent Task</i>. That is the service load, and outside 12-26 it is smaller than it feels.</div>
    <div class="line" style="border-color:var(--risk)"><span class="vs-tag">Plannable, added anyway</span><br>Most of the mid-sprint additions carry no reactive marker — dashboard tabs, E2E testing, table-layout fixes. This is the planning gap.</div>
    <div class="line" style="border-color:var(--warning)"><span class="vs-tag">Not measurable from 18-26</span><br>The label stopped being applied, so those sprints show as no data, not as zero reactive work.</div>
   </div>
  </div>
  <div class="infopanel ip-amber">One caveat on method: the label lives on the ticket, not on the moment. If someone added it after the fact, the item still counts as reactive here.</div>
 </div>

"""

def charts_scrum(mk=None, only=None):
    names = json.dumps([short_sprint(r[0]) for r in SPRINTS])
    comp  = json.dumps([r[7] for r in SPRINTS])
    comm  = json.dumps([r[5] for r in SPRINTS])
    sl_names = [n for n in SPLIT if SPLIT[n]]
    js = "" if only else f"""
const velRef={{id:'velRef',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 const yp=y.getPixelForValue({VEL_BASE});ctx.save();ctx.strokeStyle=RED;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);
 ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle=RED;ctx.font='600 10px DM Sans';ctx.textAlign='right';ctx.fillText('Baseline {VEL_BASE}',right-4,yp-4);ctx.restore();}}}};
new Chart(document.getElementById('cVel'),{{type:'bar',
 data:{{labels:{names},datasets:[
  {{label:'Committed (day 1)',data:{comm},backgroundColor:GREY,borderRadius:5}},
  {{label:'Completed',data:{comp},backgroundColor:BLUE,borderRadius:5}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,max:115,grid:{{color:gridc}},title:{{display:true,text:'Story points'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[velRef]}});
new Chart(document.getElementById('cSplit'),{{type:'bar',
 data:{{labels:{json.dumps([short_sprint(n) for n in sl_names])},datasets:[
  {{label:'Reactive (Unplanned / Urgent)',data:{json.dumps([SPLIT[n]['react'] for n in sl_names])},backgroundColor:AMBER,borderRadius:4}},
  {{label:'Plannable',data:{json.dumps([SPLIT[n]['plan'] for n in sl_names])},backgroundColor:RED,borderRadius:4}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{x:{{stacked:true,grid:{{display:false}}}},y:{{stacked:true,beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Points added mid-sprint'}}}}}}}}}});"""
    lst = only if only else (SP_BY_MONTH.get(mk, [r[0] for r in SPRINTS]) if mk else [r[0] for r in SPRINTS])
    lst = [n for n in lst if sp(n)]
    if not only:
        b = band([cl(k) for k in MK_L3])
        labs = MK_LABS
        vals = [cl(k) for k in MK_DONE]
        cur  = MONTH_LABEL.get(mk,"")[:3] if mk else ""
        cols = json.dumps(['#007CBC' if l==cur else 'var(--edge)' for l in labs])
        js += f"""
const bandRef={{id:'bandRef',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 const yl=y.getPixelForValue({b['lo']:.1f}), yh=y.getPixelForValue({b['hi']:.1f});
 ctx.save();ctx.fillStyle='rgba(79,168,0,.10)';ctx.fillRect(left,yh,right-left,yl-yh);
 ctx.strokeStyle='#4FA800';ctx.setLineDash([5,4]);ctx.lineWidth=1.2;
 [yl,yh].forEach(function(yp){{ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();}});
 ctx.setLineDash([]);ctx.fillStyle='#4FA800';ctx.font='600 10px DM Sans';ctx.textAlign='right';
 ctx.fillText('expected {b['lo']:.0f}-{b['hi']:.0f}',right-4,yh-4);ctx.restore();}}}};
new Chart(document.getElementById('cBand'),{{type:'bar',
 data:{{labels:{json.dumps(labs)},datasets:[{{label:'Items closed',data:{json.dumps(vals)},backgroundColor:{cols},borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Items closed'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[bandRef]}});"""
        ss2 = spill_series([r[0] for r in SPRINTS])
        _lb = json.dumps([short_sprint(n) for n,_ in ss2["rows"]])
        _rt = json.dumps([round(r["rate"],1) for _,r in ss2["rows"]])
        _cl = json.dumps(["#d64550" if r["rate"]>=50 else ("#ED7D31" if r["rate"]>=33 else "#65B2D5") for _,r in ss2["rows"]])
        js += f"""
const spillRef={{id:'spillRef',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 const yp=y.getPixelForValue({ss2['rate']:.1f});ctx.save();ctx.strokeStyle='var(--wf-muted)';ctx.lineWidth=1.5;ctx.setLineDash([5,4]);
 ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle='var(--wf-muted)';ctx.font='600 10px DM Sans';ctx.textAlign='right';
 ctx.fillText('series average {ss2['rate']:.0f}%',right-4,yp-4);ctx.restore();}}}};
new Chart(document.getElementById('cSpill'),{{type:'bar',
 data:{{labels:{_lb},datasets:[{{label:'Spillover rate',data:{_rt},backgroundColor:{_cl},borderRadius:5}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:100,grid:{{color:gridc}},ticks:{{callback:v=>v+'%'}},title:{{display:true,text:'% of points that left the sprint'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[spillRef]}});"""
        _cjs, _cnm = change_marks(json.loads(_lb), "spillover")
        if _cjs:
            js = js.replace("plugins:[spillRef]}});", "plugins:[spillRef," + _cnm + "]}});")
            js = js.replace("const spillRef=", _cjs + "\nconst spillRef=")

        # Received against handed on: same unit, one axis. A team that takes in as
        # much as it gives out is running a queue, and the trend is the point.
        _flow = [(n, (spill(n) or {})) for n, _ in ss2["rows"]]
        _flow = [(n, sl) for n, sl in _flow if sl.get("in") is not None]
        if _flow:
            _fl = json.dumps([short_sprint(n) for n, _ in _flow])
            _in = json.dumps([sl["in"][1] for _, sl in _flow])
            _ou = json.dumps([sl["open"][1] + sl["out"][1] for _, sl in _flow])
            js += f"""
new Chart(document.getElementById('cRecv'),{{type:'bar',
 data:{{labels:{_fl},datasets:[
  {{label:'Inherited at day 1',data:{_in},backgroundColor:BLUEL,borderRadius:4}},
  {{label:'Handed to the next sprint',data:{_ou},backgroundColor:AMBER,borderRadius:4}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{
  y:{{beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Story points'}}}},
  x:{{grid:{{display:false}}}}}}}}}});"""
            _cjs2, _cnm2 = change_marks(json.loads(_fl), "spillover")
            if _cjs2:
                js = js.replace("new Chart(document.getElementById('cRecv')",
                                _cjs2 + "\nnew Chart(document.getElementById('cRecv')")
                js = js.replace("  x:{grid:{display:false}}}}});",
                                "  x:{grid:{display:false}}}},plugins:[" + _cnm2 + "]});")

    pairs = [(n, i) for i, n in enumerate(lst)]
    if mk == MK_LAST and ACTIVE and ACTIVE not in lst and sp(ACTIVE):
        pairs.append((ACTIVE, 90))
    for n, i in pairs:
        row = sp(n); burn, scope = row[9], row[10]
        labels = json.dumps([f"d{d}" for d in range(len(burn))])
        ideal = json.dumps([round(scope[0]*(1-d/(len(burn)-1)),1) for d in range(len(burn))])
        # the line the sprint would have drawn if nothing had been taken out of it.
        # The gap between the two is work that left, not work that finished.
        _g = GHOST.get(n)
        gh = ("" if not _g or _g[-len(burn):] == burn else
              ",{label:'Open if nothing had been removed',data:" + json.dumps(_g[:len(burn)]) +
              ",borderColor:'#ED7D31',borderDash:[2,3],pointRadius:0,borderWidth:2,fill:false}")
        js += f"""
new Chart(document.getElementById('bd{i}'),{{type:'line',
 data:{{labels:{labels},datasets:[
  {{label:'Total scope',data:{json.dumps(scope)},borderColor:GREY,backgroundColor:'rgba(195,205,218,.25)',fill:true,tension:.2,pointRadius:0,borderWidth:2}},
  {{label:'Work still open',data:{json.dumps(burn)},borderColor:BLUE,backgroundColor:'rgba(0,124,188,.10)',fill:true,tension:.2,pointRadius:3,borderWidth:3}},
  {{label:'Ideal from day-1 commitment',data:{ideal},borderColor:'var(--edge)',borderDash:[5,4],pointRadius:0,borderWidth:2,fill:false}}{gh}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Story points'}}}},x:{{grid:{{display:false}},title:{{display:true,text:'Sprint day'}}}}}}}}}});"""
    return js

def month_page(mk):
    m = MONTHS[mk]
    _tis_card, _tis_js = tis_trend_card()
    cm  = cap([mk]); cq1 = cap(CAP_Q1); cq2 = cap(CAP_Q2)
    bnd = band([cl(k) for k in MK_L3])
    in_band = bnd["lo"] <= cl(mk) <= bnd["hi"]
    st_thr = "healthy" if in_band else "warning"
    # A month in progress is compared at pace, never as a total: 29 items on day 15
    # is not "29 against 82", it is a run rate. The baselines are cut to the same
    # share of the month so the two sides of the comparison cover the same ground.
    OPEN = bool(m.get("open"))
    SHARE = (m.get("day", 30) / m.get("days", 30)) if OPEN else 1.0
    PACE = m["closed"] / SHARE if SHARE else m["closed"]
    pace_note = ('' if not OPEN else
        f'<div class="ctxline"><span>At this pace the {PERIOD_WORD} lands near <b>{PACE:.0f} items</b>. '
        f'Every comparison below is cut to the same {100*SHARE:.0f}% on both sides.</span></div>')
    # A reference of zero has no percentage to be off by. It happens at the head of
    # a series -- the first release has no previous one -- and it would happen again
    # for any period that closed nothing. Zero comes back as no deviation rather
    # than as a crash; the number itself is still printed beside it.
    def _dev(now, ref):
        ref = (ref or 0) * SHARE
        return ((now - ref) / ref * 100) if ref else 0.0
    dev_base = _dev(m["closed"], Q1["thr_med"])
    dev_q2   = _dev(m["closed"], Q2["thr_med"])
    dev_prev = _dev(m["closed"], m["prev_closed"])
    types = " · ".join(f"{n} {t}" for t,n in m["types"])

    # unplanned card
    if m["unplanned"] is None:
        unp_card = f"""<div class="card">
      <div class="ghead"><span class="gname">Planned vs Unplanned</span><span class="badge" style="background:var(--pillbg);color:var(--wf-muted2)"><span class="d" style="background:var(--muted3)"></span>No data</span></div>
      <div class="nodata" style="margin:10px 0"><span class="big">—</span>0 items labeled <i>Unplanned</i> {"so far this " + PERIOD_WORD if m.get("open") else "in the whole " + PERIOD_WORD}</div>
      <div class="targetline"><span class="tl">Target</span> &le;5% · Warning 5-10% · Risk &gt;10%</div>
      <div class="infopanel ip-amber">Zero labels in a {PERIOD_WORD} of {m['closed']} deliveries does not mean zero reactive work: it means the labeling stopped being applied. Publishing 0% would invent an improvement the team did not have. The labeling follow-up has been open since the May retro.</div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('unp', 'Planned vs Unplanned — Team Guide')}</div>"""
    else:
        ust = "healthy" if m["unp_pct"] <= 5 else ("warning" if m["unp_pct"] <= 10 else "risk")
        ip = {"healthy":"ip-green","warning":"ip-amber","risk":"ip-red"}[ust]
        col = {"healthy":"num-green","warning":"num-amber","risk":"num-red"}[ust]
        unp_card = f"""<div class="card">
      <div class="ghead"><span class="gname">Planned vs Unplanned</span>{badge(ust)}</div>
      <div class="bignum {col}">{m['unp_pct']:.1f}<span class="unit">%</span></div>
      <div class="secondary">{m['unplanned']} of {m['closed']} deliveries labeled Unplanned</div>
      <div class="targetline"><span class="tl">Target</span> &le;5% · Warning 5-10% · Risk &gt;10%</div>
      {sb_rows([("Unplanned share", f"{m['unp_pct']:.1f}%", pdelta(m['unp_pct'],Q1['unp']), pdelta(m['unp_pct'],Q2['unp']), True),
                ("Items", f"{m['unplanned']}", None, None, True)])}
      <div class="ctxline"><span>{REF1_SHORT} <b>{_pct(Q1['unp'])}</b> &middot; {REF2_SHORT} <b>{_pct(Q2['unp'])}</b></span></div>
      <div class="infopanel {ip}"><a href="#" class="ip-link" data-goto="act">See the breakdown in Findings &amp; Retro &rarr;</a></div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('unp', 'Planned vs Unplanned — Team Guide')}</div>"""

    # WIP card - live only on the latest month, and only where a snapshot exists.
    # WIP is the one metric no job can reconstruct: it is a reading taken at a
    # moment, and a team that has never taken one has no WIP, which is a different
    # statement from WIP being zero. Without it the card says so.
    if mk == MK_LAST and WIP:
        w = dict(WIP)
        _d = ((LIVE or {}).get("sprint") or {}).get("dist") or {}
        if _d:                      # count what is actually in flight right now
            w["dev"] = _d.get("In Development", 0)
            w["rev"] = _d.get("Awaiting Review", 0)
            w["total"] = w["dev"] + w["rev"]
        wip_card = f"""<div class="card wipcard">
      <div class="ghead"><span class="gname">Work In Progress · current snapshot</span>{badge('healthy')}</div>
      <div class="wiptotal"><div class="wt-num">{w['total']}<span class="wt-den">/ {w['lim_tot']}</span></div>
      <div class="wt-lbl">items in progress<br><b>{100*w['total']//w['lim_tot']}% of the limit</b></div></div>
      <div class="wipwrap">
        <div class="wiprow"><span class="nm">In Development</span><div class="wipbar"><div class="wipfill" style="width:{100*w['dev']//w['lim_dev']}%">{w['dev']}</div></div><span class="wiplim">/ &le;{w['lim_dev']}</span></div>
        <div class="wiprow"><span class="nm">Awaiting Review</span><div class="wipbar"><div class="wipfill" style="width:{100*w['rev']//w['lim_rev']}%">{w['rev']}</div></div><span class="wiplim">/ &le;{w['lim_rev']}</span></div>
      </div>
      <div class="infopanel ip-amber"><b>Limits recalculated.</b> With Dipika leaving, the team went from 6 to {w['devs']} devs, so the 2-per-dev policy drops from 12/6/18 to {w['lim_dev']}/{w['lim_rev']}/{w['lim_tot']}. Measured against the old limits this would look roomier than it really is.</div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('wip', 'WIP — Team Guide')}</div>"""
    else:
        wip_card = f"""<div class="card wipcard">
      <div class="ghead"><span class="gname">Work In Progress</span><span class="badge" style="background:var(--pillbg);color:var(--wf-muted2)"><span class="d" style="background:var(--muted3)"></span>No data</span></div>
      <div class="nodata" style="margin:10px 0"><span class="big">—</span>historical snapshot not captured</div>
      <div class="infopanel ip-amber">WIP is a point-in-time reading, not a monthly aggregate. It was not captured at the close of {m['label'].split()[0]}, and Jira cannot rebuild it backwards without the Cumulative Flow Diagram.{" The current snapshot lives in the latest report." if WIP else ""}</div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('wip', 'WIP — Team Guide')}</div>"""

    # Every cell here can be absent on its own: the period may carry no label at
    # all, and either reference may not exist yet. A percentage-point difference
    # against a reference that is not there is not zero, it is nothing.
    def _pp(now, ref):
        if ref is None:
            return '<td class="flat">\u2014</td>'
        d = now - ref
        return f'<td class="{"pos" if d < 0 else "neg"}">{d:+.1f} pp</td>'
    _r1 = f'{Q1["unp"]}%' if Q1["unp"] is not None else "\u2014"
    _r2 = f'{Q2["unp"]}%' if Q2["unp"] is not None else "\u2014"
    if m["unplanned"] is None:
        unp_row = (f'<td class="flat">no data</td><td class="flat">\u2014</td><td>{_r1}</td>'
                   f'<td>{_r2}</td><td class="flat">\u2014</td><td class="flat">\u2014</td>')
    else:
        unp_row = (f'<td>{m["unp_pct"]:.2f}%</td><td class="flat">\u2014</td><td>{_r1}</td><td>{_r2}</td>'
                   + _pp(m["unp_pct"], Q1["unp"]) + _pp(m["unp_pct"], Q2["unp"]))

    tickets = "".join(f'<div class="ticket"><span class="tkey">{k}</span><span class="tdesc">{s}</span></div>'
                      for k,s in m["unp_items"])
    if m["unp_items"]:
        obs_block = f"""<div class="cmpcard">
     <div class="cmphead"><h3>The {m['unplanned']} items labeled Unplanned</h3></div>
     {tickets}
     <div class="fnote">{m.get("note_unp") or f"{m['unplanned']} of the {m['closed']} items closed this month came in labeled Unplanned or typed Urgent Task."}</div>
   </div>"""
    else:
        obs_block = f"""<div class="cmpcard">
     <div class="cmphead"><h3>No unplanned-work data</h3></div>
     <div class="nodata"><span class="big">0 labels</span>across {m['closed']} deliveries {"so far this " + PERIOD_WORD if m.get("open") else "this " + PERIOD_WORD}</div>
     <div class="fnote">{m.get("note_unp") or f"Zero labels across {m['closed']} deliveries describes the labeling, not the work. Without this label the predictability metric stops existing, and it is the only one that explains why a month with good throughput can still be unstable."}</div>
   </div>"""

    disc_note = ""
    if m["discarded"] >= 5:
        pct_d = (100*m["discarded"]/m["resolved"]) if m["resolved"] else 0.0
        disc_note = f"""<div class="act"><div class="pri p-grey"></div><div class="inner">
     <div class="atop"><h4>Review the {m['discarded']} discarded items</h4><span class="pill pill-grey">Follow-up</span></div>
     <p>The official Throughput filter uses <i>resolved</i>, which mixes closed with discarded (Won't Do). This {PERIOD_WORD} that is {m['discarded']} of {m['resolved']} resolved ({pct_d:.0f}%), which is why the headline counts only the {m['closed']} closed. Worth looking at in the retro at what was opened and then dropped — it usually signals work that came in without enough definition.</p>
     <div class="owner">Follow-up by: <b>{TKEY}</b></div></div></div>"""

    ip_thr = {"healthy":"ip-green","warning":"ip-amber","risk":"ip-red"}[st_thr]
    col_thr = {"healthy":"num-green","warning":"num-amber","risk":"num-red"}[st_thr]
    c = CYC[mk]
    cyc_st = cyc_status(c)
    col_cyc = {"healthy":"num-green","warning":"num-amber","risk":"num-red"}[cyc_st]
    nodev_pct = 100*c["nodev"]/c["base"] if c["base"] else 0
    _ref_k = CYC_ORDER[0] if CYC_ORDER else None
    _nodev_ref = (f"In {MONTH_LABEL.get(_ref_k, _ref_k)} it was {CYC[_ref_k]['nodev']} of {CYC[_ref_k]['base']} "
                  f"({100*CYC[_ref_k]['nodev']/CYC[_ref_k]['base']:.0f}%)."
                  if _ref_k and _ref_k != mk and CYC.get(_ref_k, {}).get("base") else "")
    # series de comparativas, generadas de los periodos que existen
    _keys   = [k for k in MK_ALL]
    _thr_l  = json.dumps([MONTH_LABEL.get(k, k) for k in _keys])
    _thr_d  = json.dumps([round(cl(k), 1) for k in _keys])
    _thr_c  = json.dumps(["#007CBC" if k == mk else "#65B2D5" for k in _keys])
    _thr_max = max([cl(k) for k in _keys] + [1]) * 1.25
    # A reference with no figure is dropped from the chart rather than plotted as
    # zero: an absent median is not a fast one.
    _ck     = [k for k in CYC_ORDER]
    _refs   = [(lab, Q["cyc_med"], Q["cyc_avg"])
               for lab, Q in ((REF1_SHORT, Q1), (REF2_SHORT, Q2))
               if Q["cyc_med"] is not None and Q["cyc_avg"] is not None]
    _cyc_l  = json.dumps([r[0] for r in _refs] + [MONTH_LABEL.get(k, k) for k in _ck])
    _cyc_m  = json.dumps([r[1] for r in _refs] + [CYC[k]["med"] for k in _ck])
    _cyc_a  = json.dumps([r[2] for r in _refs] + [CYC[k]["avg"] for k in _ck])
    _cyc_max = max([r[2] for r in _refs] + [CYC[k]["avg"] for k in _ck] + [1]) * 1.2
    # Unplanned had a hand-written series here -- fixed labels and two figures typed
    # into the code. It described EDW's Jun/Jul and nothing else, so a second team
    # would have published EDW's reactive work as its own. Derived like the two
    # charts above now: the periods that exist, and null where the label was not
    # applied, so the line breaks instead of reading as zero.
    _unp_v  = [(RELEASES.get(k) or {}).get("unp_pct") if RELEASES else None for k in _keys]
    _unp_l  = json.dumps([MONTH_LABEL.get(k, k) for k in _keys])
    _unp_d  = json.dumps(_unp_v)
    # the dot colours are JS constants, so they go in as bare identifiers; a
    # json.dumps here would quote them and Chart.js would draw nothing
    _unp_c  = "[" + ",".join("GREY" if v is None else
                             "GREEN" if v <= 5 else "AMBER" if v <= 10 else "RED"
                             for v in _unp_v) + "]"
    _unp_max = max([v for v in _unp_v if v is not None] + [15]) * 1.25
    # the readout under the chart said the same thing in prose, and it was typed in:
    # a fixed Q1/Q2/May/Jun/Jul/Aug series with EDW's figures. It now reads off the
    # same list the chart plots, so the two cannot drift apart, and the warning
    # names whichever periods are missing the label instead of naming August.
    _unp_series = " &rarr; ".join(
        f"{MONTH_LABEL.get(k, k)} {'no data' if v is None else f'{v}%'}"
        for k, v in zip(_keys, _unp_v)) + "."
    _gapn = [MONTH_LABEL.get(k, k) for k, v in zip(_keys, _unp_v) if v is None]
    _unp_gap = ('<div class="line" style="border-color:var(--warning)">'
                '<span class="vs-tag">Careful</span><br>'
                + ("The break at " + _plist(_gapn) + " is not a drop to zero, it is "
                   "missing labeling. The line is interrupted on purpose.")
                + '</div>') if _gapn else ""

    # A release that has not closed gets no flow-health verdict. Every number on the
    # page is still moving -- items keep closing, cycle time is computed over the
    # subset that has finished -- and a verdict on a partial period is a verdict on
    # the calendar. It is the same rule the sprint page already keeps.
    if m.get("open"):
        _done = m.get("sprints_done")
        _pill = ("Release in progress"
                 + (f" — {_done} of {m['n_sprints']} sprints closed" if _done is not None
                    else f" — {m['n_sprints']} sprints")
                 + f" · ends {_fmt_day(m['end'])}. The numbers move until it closes, so this "
                   "page carries no flow-health verdict yet.")
        _pst = "open"
    else:
        _pill = f"Flow Health: {BADGE[m['status']][1].upper()} — {m['headline']}"
        _pst  = m["status"]

    html = head(f"{m['label']} Performance Report",
                f"Flow and sprint metrics for the {PERIOD_WORD}, against {m['prev']} and {globals().get('REF2_PHRASE', REF2_LABEL)}.",
                _pill, _pst, m["short"])

    html += f"""
<section class="panel active" id="dash">
  <div class="sectit">Flow metrics — {m['label']}</div>
  <div class="secsub">Throughput counts closed items only; discarded work is reported separately.</div>
  <div class="grid g3">
    <div class="card">
      <div class="ghead"><span class="gname">Throughput</span>{badge(st_thr)}</div>
      <div class="bignum {col_thr}">{m['closed']}<span class="unit">{"closed · day " + str(m.get("day")) + " of " + str(m.get("days")) if OPEN else "closed · " + PERIOD_WORD}</span></div>
{pace_note}
      <div class="secondary">{types}</div>
      {sb_rows([("Items closed", f"{cm['items']:.0f}", _vs(cm['items'], cq1['items'], SHARE), _vs(cm['items'], cq2['items'], SHARE), False),
                ("Story points", f"{cm['pts']:.0f}", _vs(cm['pts'], cq1['pts'], SHARE), _vs(cm['pts'], cq2['pts'], SHARE), False)])}
      <div class="ctxline"><span>Average item size <b>{_num(cm['size'])} pts</b> <i>({REF1_SHORT} {_num(cq1['size'])})</i></span>
        <span>Team <b>{cm['people']:.0f} active</b> <i>({REF1_SHORT} {_num(cq1['people'], "{:.1f}")})</i></span></div>
      <div class="spark-cap">{_spark_cap(mk)}</div>
      {spark([cl(k) for k in MK_DONE], _sidx(mk)) if MK_DONE else ""}
      <div class="infopanel {ip_thr}">On top of the {m['closed']} closed there were <b>{m['discarded']} discarded</b> (Won't Do), which are not deliveries.
{_thr_vs_line(cm, cq1, SHARE, OPEN)}
        <a href="#" class="ip-link" data-goto="cmp">Trend and expected range in Comparatives &rarr;</a></div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('thr', 'Throughput — Team Guide')}
    </div>
    <div class="card">
      <div class="ghead"><span class="gname">Cycle Time</span>{badge(cyc_st)}</div>
      <div class="bignum {col_cyc}">{c['med']:.2f}<span class="unit">d median</span></div>
      <div class="secondary">{c['n']} issues measured · longest {c['mx']:.0f}d</div>
      <div class="targetline"><span class="tl">Target</span> &le;6d median · &le;9d average</div>
      {sb_rows([("Median", f"{c['med']:.1f}d", _dv(c['med'], Q1['cyc_med']), _dv(c['med'], Q2['cyc_med']), True),
                ("Average", f"{c['avg']:.1f}d", _dv(c['avg'], Q1['cyc_avg']), _dv(c['avg'], Q2['cyc_avg']), True)])}
      <div class="ctxline"><span>Measured on <b>{c['n']} of {c['base']}</b> closed items <i>({_num(100*c['n']/c['base'] if c['base'] else None, "{:.0f}")}% of the {PERIOD_WORD})</i></span></div>
      <div class="spark-cap">Median cycle time · {_plabel(CYC_ORDER[0]) if CYC_ORDER else ""} to {_plabel(CYC_ORDER[-1]) if CYC_ORDER else ""}</div>
      {spark([CYC[k]['med'] for k in CYC_ORDER], CYC_ORDER.index(_cyckey(mk)) if _cyckey(mk) in CYC_ORDER else None, col="#4FA800")}
      <div class="infopanel ip-green">Median and average both within target. The gap between {c['med']:.1f}d and {c['avg']:.1f}d comes from a few long tickets — the longest this month took {c['mx']:.0f} days.</div>
      <div class="cardfill"></div><hr class="docsep">
      {doclink('cycle', 'Cycle Time — Team Guide')}
    </div>
    {unp_card}
  </div>
  <div class="grid g2" style="margin-top:18px">
    <div class="card mixcard">
      <div class="ghead" style="width:100%"><span class="gname">Delivered vs discarded</span></div>
      <div class="mixbody"><div class="donutwrap"><canvas id="donut"></canvas>
        <div class="donutctr"><div class="dc-num">{m['closed']}</div><div class="dc-lbl">of {m['resolved']}<br>closed</div></div></div>
        <div class="mixlegend">
          <div class="ml-row"><span class="ml-sw" style="background:#007CBC"></span><span class="ml-nm">Closed</span><span class="ml-val">{m['closed']}</span></div>
          <div class="ml-row"><span class="ml-sw" style="background:var(--edge)"></span><span class="ml-nm">Won't Do</span><span class="ml-val">{m['discarded']}</span></div>
        </div></div>
      <div class="infopanel ip-amber">May closed 39 without a single discard. From June on, discards show up every month.</div>
      <div class="cardfill"></div>
    </div>
    {wip_card}
  </div>

  <div style="margin-top:26px"></div>
  <div class="sectit" style="font-size:20px">Executive summary</div>
  <div class="tscroll"><table class="exec">
    <thead><tr><th>Metric</th><th>{m['label'].split()[0]}</th><th>{m['prev']}</th><th>{REF1_LABEL}</th><th>{REF2_LABEL}</th><th>vs {REF1_SHORT}</th><th>vs {REF2_SHORT}</th></tr></thead>
    <tbody>
      <tr><td>Throughput (closed)</td><td>{m['closed']}</td><td>{m['prev_closed']}</td><td>{Q1['thr_med']}</td><td>{Q2['thr_med']}</td><td class="{'pos' if dev_base>0 else 'neg'}">{dev_base:+.1f}%</td><td class="{'pos' if dev_q2>0 else 'neg'}">{dev_q2:+.1f}%</td></tr>
      <tr><td>Unplanned work</td>{unp_row}</tr>
      <tr><td>Cycle Time (median)</td><td>{c['med']:.2f}d</td><td class="flat">—</td><td>{_days(Q1['cyc_med'])}</td><td>{_days(Q2['cyc_med'])}</td>{_pcell(c['med'], Q1['cyc_med'], True)}{_pcell(c['med'], Q2['cyc_med'], True)}</tr>
      <tr><td>Closed without entering development</td><td>{c['nodev']} ({nodev_pct:.0f}%)</td><td class="flat">—</td><td class="flat">—</td><td>{Q2['nodev']}</td><td class="flat">—</td><td class="flat">—</td></tr>
    </tbody>
  </table></div>
  <div class="fnote">Comparatives use the closed quarters of the year: Q1 and Q2. Q3 joins this table once September closes and its report is created. Q1's monthly detail is under review — the figure used here is the one published in Confluence.</div>
  {tis_flow_block(mk)}
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    {rlink('dash', '&#128216;', 'How to read the dashboard')}
    {rlink('q1', '&#128208;', 'Q1 2026 Baseline')}
    {quarterlink()}
    {dashlink()}
  </div></div>
</section>

{scrum_tab(mk)}
<section class="panel" id="cmp">
  <div class="sectit">Comparatives</div>
  <div class="secsub">The full series from the baseline, so the trend shows and not just the month. Same order as the Flow tab: what came out, how long it took, where that time went, and how much of it was reactive.</div>
  <div class="cmpcard">
    <div class="cmphead"><h3><span class="st-dot" style="background:{BADGE[st_thr][2]};width:13px;height:13px"></span> Throughput</h3>{badge(st_thr)}</div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cThru"></canvas></div>
      <div class="readout">
        <div class="line" style="border-color:{BADGE[st_thr][2]}"><span class="vs-tag">vs {REF1_SHORT} ({Q1['thr_med']}{Q1.get('unit','/mo')})</span><br><b>{dev_base:+.1f}%</b> in items{_per_clause(cm, cq1)}</div>
        <div class="line" style="border-color:{BADGE[st_thr][2]}"><span class="vs-tag">vs {REF2_SHORT} ({Q2['thr_med']}{Q2.get('unit','/mo')})</span><br><b>{dev_q2:+.1f}%</b>{Q2.get('note',' — and Q2 is a poor yardstick anyway: its median is set by April and May, under the previous team.')}</div>
        <div class="line"><span class="vs-tag">Reading</span><br>Throughput scales with headcount, so a fixed baseline cannot survive a team change. The status on this page comes from the expected range below, not from the distance to Q1.</div>
      </div>
    </div>
  </div>
  <div class="cmpcard">
    <div class="cmphead"><h3><span class="st-dot" style="background:{BADGE[cyc_st][2]};width:13px;height:13px"></span> Cycle Time</h3>{badge(cyc_st)}</div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cCyc"></canvas></div>
      <div class="readout">
        <div class="line" style="border-color:{BADGE[cyc_st][2]}"><span class="vs-tag">Method</span><br>Rebuilt from Jira history: from the first entry into <i>In Development</i> to closure, in calendar days.</div>
        <div class="line"><span class="vs-tag">Comparability note</span><br>Applied to May it gives a <b>5.18d</b> median against the <b>4.83d</b> published. The Control Chart summed only the time inside the board columns; this method measures elapsed time end to end and includes bounce-backs. The series is consistent with itself, but runs slightly above the historical one.</div>
      </div>
    </div>
  </div>
  {_tis_card}
  <div class="cmpcard">
    <div class="cmphead"><h3>Planned vs Unplanned</h3></div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cUnp"></canvas></div>
      <div class="readout">
        <div class="line"><span class="vs-tag">The series</span><br>{_unp_series}</div>
        {_unp_gap}
      </div>
    </div>
  </div>
  {series_block()}
</section>
{findings_panel(mk)}"""

    charts = f"""
new Chart(document.getElementById('donut'),{{type:'doughnut',
 data:{{labels:['Cerrados',"Won't Do"],datasets:[{{data:[{m['closed']},{m['discarded']}],backgroundColor:[BLUE,GREY],borderColor:'#fff',borderWidth:3}}]}},
 options:{{cutout:'68%',responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}}}}}});
const thrRef={{id:'thrRef',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 [{{v:{Q1['thr_med']},t:'Q1 {Q1["thr_med"]}',col:BLUED}},{{v:{Q2['thr_med']},t:'Q2 {Q2["thr_med"]}',col:AMBER}}].forEach(r=>{{
  const yp=y.getPixelForValue(r.v);ctx.save();ctx.strokeStyle=r.col;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);
  ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=r.col;ctx.font='600 10px DM Sans';ctx.textAlign='right';ctx.fillText(r.t,right-4,yp-4);ctx.restore();}});}}}};
new Chart(document.getElementById('cThru'),{{type:'bar',
 data:{{labels:{_thr_l},datasets:[{{label:'Closed',
  data:{_thr_d},backgroundColor:{_thr_c},borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:{_thr_max:.0f},grid:{{color:gridc}},title:{{display:true,text:'Items closed{" per sprint" if PERIOD_WORD=="release" else ""}'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[thrRef]}});
new Chart(document.getElementById('cCyc'),{{type:'bar',
 data:{{labels:{_cyc_l},datasets:[
  {{label:'Median',data:{_cyc_m},backgroundColor:BLUE,borderRadius:5}},
  {{label:'Average',data:{_cyc_a},backgroundColor:BLUEL,borderRadius:5}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,max:{_cyc_max:.0f},grid:{{color:gridc}},title:{{display:true,text:'Days'}}}},x:{{grid:{{display:false}}}}}}}}}});
const bands={{id:'bands',beforeDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;const z=v=>y.getPixelForValue(v);
 ctx.save();ctx.fillStyle='rgba(79,168,0,.08)';ctx.fillRect(left,z(5),right-left,z(0)-z(5));
 ctx.fillStyle='rgba(237,125,49,.12)';ctx.fillRect(left,z(10),right-left,z(5)-z(10));
 ctx.fillStyle='rgba(214,69,80,.08)';ctx.fillRect(left,z(20),right-left,z(10)-z(20));ctx.restore();}}}};
new Chart(document.getElementById('cUnp'),{{type:'line',
 data:{{labels:{_unp_l},datasets:[{{data:{_unp_d},
  borderColor:BLUED,backgroundColor:BLUED,tension:.25,pointRadius:6,borderWidth:3,spanGaps:false,
  pointBackgroundColor:{_unp_c}}}]}},
 options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>c.raw==null?' no data':` ${{c.raw}}% unplanned`}}}}}},
  scales:{{y:{{beginAtZero:true,max:{_unp_max:.0f},grid:{{color:gridc}},ticks:{{callback:v=>v+'%'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[bands]}});
{charts_scrum(mk)}""" + _tis_js
    return html + _fill(FOOT).replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)

def q2_page():
    apr, may, jun = APR, MAY, 74
    tot = apr + may + jun
    med = sorted([apr,may,jun])[1]
    avg = round(tot/3, 1)
    html = head("Q2 2026 Performance Report",
                "Quarter close for April-June 2026, compared against Q1.",
                "Quarter close — the Q2 team is not the Q1 team", "warning", "Q2")
    html += f"""
<section class="panel active" id="dash">
  <div class="sectit">Q2 2026 — April to June</div>
  <div class="secsub">Same method as the Q1 baseline: closed items, excluding sub-tasks and epics.</div>
  <div class="grid g3">
    <div class="card"><div class="ghead"><span class="gname">Throughput Q2</span></div>
      <div class="bignum num-green">{med}<span class="unit">median/mo</span></div>
      <div class="secondary">{tot} closed in the quarter · average {avg}</div>
      <div class="targetline"><span class="tl">Q1</span> median {Q1['thr_med']} · average {Q1['thr_avg']}</div>
      <div class="infopanel ip-amber">Q2's median ({med}) lands almost on top of Q1's ({Q1['thr_med']}), but it hides the break: April and May ran at 36 and 39, and June jumped to 74. The quarter mixes two different teams.</div>
      <div class="cardfill"></div><hr class="docsep">{doclink('thr', 'Throughput — Team Guide')}</div>
    <div class="card"><div class="ghead"><span class="gname">Team composition</span></div>
      <div class="bignum num-blue">4 &rarr; 6 &rarr; 5<span class="unit">devs</span></div>
      <div class="secondary">Q1 · May-July · from August</div>
      <div class="infopanel ip-amber">Harisha and Shruti picked up their first ticket on May 18 and 20. Dipika left in early August. No baseline crossing those dates describes a single team.</div>
      <div class="cardfill"></div></div>
    <div class="card"><div class="ghead"><span class="gname">Q2 unplanned work</span>{badge('risk')}</div>
      <div class="bignum num-red">{Q2['unp']}<span class="unit">% of the quarter</span></div>
      <div class="secondary">{Q2['unp_n']} of {Q2['closed']} closed · April 2.78% · May 17.95% · June 6.76%</div>
      <div class="targetline"><span class="tl">Q1</span> {Q1['unp']}% · <span class="tl">Target</span> &le;5%</div>
      <div class="infopanel ip-red">Q2 nearly doubles Q1 and with far more variance. May is the peak; June comes down but stays above target. The percentage is over the quarter total, not the average of the three months.</div>
      <div class="cardfill"></div><hr class="docsep">{doclink('unp', 'Planned vs Unplanned — Team Guide')}</div>
  </div>
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    {rlink('dash', '&#128216;', 'How to read the dashboard')}
    {rlink('q1', '&#128208;', 'Q1 2026 Baseline')}
    {rlink('thr', '&#128202;', 'Throughput — Team Guide')}
    {dashlink()}
  </div></div>
  <div class="fnote">Two caveats on this baseline: August has no unplanned-work data, and all three months include discards (Won't Do) that did not appear before. The Q1 row is now the reconciled figure: recalculated with the official filter, Q1 closed <b>120</b> items (44/36/40), an average of 40 a month. The 100 (10/45/45) published in the Confluence report could not be reproduced under any filter variant and has been corrected at the source — see the recalculation notice on that page.</div>
</section>
{scrum_tab()}
<section class="panel" id="cmp">
  <div class="sectit">Comparatives</div>
  <div class="secsub">Q2 against Q1 and against the rest of the year, and which reference to measure the months against.</div>
  <div class="grid g2" style="margin-top:18px">
   <div class="cmpcard"><div class="cmphead"><h3>Q1 vs Q2 month by month</h3></div>
    <div class="chartbox" style="height:270px"><canvas id="cQ"></canvas></div></div>
   <div class="cmpcard"><div class="cmphead"><h3>Which baseline to use</h3></div>
    <div class="readout">
     <div class="line" style="border-color:var(--risk)"><span class="vs-tag">Don't use Q2 as a whole</span><br>It mixes 4 devs (April, May) with 6 devs (June). A median over that describes neither stage.</div>
     <div class="line" style="border-color:var(--healthy)"><span class="vs-tag">Proposal</span><br>Take <b>June to August</b> as the working baseline: median <b>79</b> deliveries/month, healthy range 67-91 (&plusmn;15%). Those are the three months with the current headcount and a comparable working regime.</div>
     <div class="line"><span class="vs-tag">Velocity</span><br>Same cut: average of the last 5 closed sprints = <b>81.2 points</b>, against the documented baseline of {VEL_BASE}.</div>
     <div class="line" style="border-color:var(--healthy)"><span class="vs-tag">Cycle Time Q2</span><br>Median <b>{Q2['cyc_med']}d</b> and average <b>{Q2['cyc_avg']}d</b> over 125 items, against {Q1['cyc_med']}d / {Q1['cyc_avg']}d in Q1. This is the metric that did improve cleanly between quarters.</div>
     <div class="line"><span class="vs-tag">Review</span><br>At the Q3 close, and whenever headcount changes.</div>
    </div></div>
  </div>
  <div style="margin-top:26px"></div>
  <div class="sectit" style="font-size:20px">Baseline comparison</div>
  <div class="tscroll"><table class="exec">
   <thead><tr><th>Reference</th><th>Period</th><th>Devs</th><th>Median/mo</th><th>Healthy range</th><th>Status</th></tr></thead>
   <tbody>
    <tr><td>Q1 2026 Baseline</td><td>Jan - Mar</td><td>4</td><td>{Q1['thr_med']}</td><td>{Q1['rng']}</td><td>in use on the dashboard</td></tr>
    <tr><td>Q2 2026</td><td>Apr - Jun</td><td>4 &rarr; 6</td><td>{med}</td><td>—</td><td>not usable, mixed quarter</td></tr>
    <tr><td><b>Proposed</b></td><td>Jun - Aug</td><td>6 &rarr; 5</td><td><b>79</b></td><td>67-91</td><td>to validate with the team</td></tr>
   </tbody>
  </table></div>
</section>
<section class="panel" id="act"><div class="sectit">Findings &amp; retro</div>
 <div class="secsub">What to do with this baseline.</div>
 <div class="insightbox"><div class="k">Quarter takeaway</div>
  <h2>Q2 does not work as a baseline because it contains the team change, not because the numbers are wrong.</h2>
  <p>Q2's median lands almost exactly on Q1's, and that coincidence is misleading: the quarter averages two months of the old team with one of the new. The useful cut is not quarterly but by headcount, and that cut falls in May.</p></div>
 <div class="act"><div class="pri p-blue"></div><div class="inner">
  <div class="atop"><h4>Adopt Jun-Aug as the working baseline</h4><span class="pill pill-blue">Discuss</span></div>
  <p>Median of 79 deliveries a month with a 67 to 91 range. It replaces the {Q1['thr_med']} in the dashboard cards and in the status thresholds.</p>
  <div class="owner">To agree with: <b>EDW</b></div></div></div>
 <div class="act"><div class="pri p-blue"></div><div class="inner">
  <div class="atop"><h4>Recalculate Velocity at the same time</h4><span class="pill pill-blue">Discuss</span></div>
  <p>From {VEL_BASE} to ~81 points a sprint. Worth doing alongside the 100%-completion conversation: if commitment is set low, the observed Velocity is not real capacity either.</p>
  <div class="owner">For discussion with: <b>EDW</b></div></div></div>
</section>"""
    charts = f"""
new Chart(document.getElementById('cQ'),{{type:'bar',
 data:{{labels:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug'],
  datasets:[{{label:'Items closed',data:[44,36,40,{APR},{MAY},74,79,82],
   backgroundColor:['var(--edge)','var(--edge)','var(--edge)','#65B2D5','#65B2D5','#007CBC','#007CBC','#007CBC'],borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:110,grid:{{color:gridc}},title:{{display:true,text:'Items closed'}}}},x:{{grid:{{display:false}}}}}}}}}});
{charts_scrum()}"""
    return html + _fill(FOOT).replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)

def q1_page():
    q1n = [r[0] for r in SPRINTS_Q1]
    vel = [r[7] for r in SPRINTS_Q1]
    vel_avg = round(sum(vel)/len(vel), 1)
    pcts = [round(100*r[7]/r[5]) for r in SPRINTS_Q1]
    chgs = [r[8] for r in SPRINTS_Q1]
    intro = f'''
 <div class="insightbox" style="margin-bottom:24px"><div class="k">What the Q1 sprints show</div>
  <h2>Every sprint delivered between {min(pcts)}% and {max(pcts)}% of what it committed to on day 1.</h2>
  <p>Scope grew between +{min(chgs)}% and +{max(chgs)}% mid-sprint — modest next to the +76% to +279% the same board shows
  from April on. The pattern that later becomes a problem is already here in a milder form: the team commits low and
  fills the sprint as it runs, so completion against commitment reads above 100% while the commitment itself means
  little. Average delivered across the seven sprints is <span class="stat">{vel_avg} points</span>, though one sprint
  (R9.00-S5, 111 points) carries most of January on its own.</p>
 </div>'''
    html = head("Q1 2026 Performance Report",
                "Quarter close for January-March 2026 — the reference baseline for the year.",
                "Baseline quarter — reconciled September 2026", "healthy", "Q1")
    html += f"""
<section class="panel active" id="dash">
  <div class="sectit">Q1 2026 — January to March</div>
  <div class="secsub">Closed items only, sub-tasks and epics excluded. Figures reconciled September 2026.</div>
  <div class="grid g3">
    <div class="card"><div class="ghead"><span class="gname">Throughput</span>{badge('healthy')}</div>
      <div class="bignum num-green">{Q1['thr_avg']}<span class="unit">avg/month</span></div>
      <div class="secondary">{Q1['closed']} closed in the quarter · Jan {Q1['months'][0]} · Feb {Q1['months'][1]} · Mar {Q1['months'][2]}</div>
      <div class="targetline"><span class="tl">Healthy range</span> {Q1['rng']} items/month (&plusmn;20%)</div>
      <div class="infopanel ip-green">A flat quarter: the spread between the best and the worst month is 8 items, which
      is what makes it usable as a baseline. On top of the {Q1['closed']} closed there were <b>{Q1_WONTDO} discarded</b>
      (Won't Do), which are not deliveries. Note that this baseline describes a 4-developer team.</div>
      <div class="cardfill"></div><hr class="docsep">{doclink('thr', 'Throughput — Team Guide')}</div>
    <div class="card"><div class="ghead"><span class="gname">Planned vs Unplanned</span>{badge('healthy')}</div>
      <div class="bignum num-green">{Q1_UNP_PCT:.2f}<span class="unit">%</span></div>
      <div class="secondary">{Q1_UNP_N} of {Q1['closed']} closed · Jan 1 · Feb 2 · Mar 2</div>
      <div class="targetline"><span class="tl">Target</span> &le;5%</div>
      <div class="infopanel ip-green">Comfortably inside target and the most stable metric of the quarter: never more
      than 2 unplanned items in a month. This is the reference the later months are measured against.</div>
      <div class="cardfill"></div><hr class="docsep">{doclink('unp', 'Planned vs Unplanned — Team Guide')}</div>
    <div class="card"><div class="ghead"><span class="gname">Cycle Time</span>{badge('warning')}</div>
      <div class="bignum num-amber">{Q1['cyc_med']}<span class="unit">d median</span></div>
      <div class="secondary">Average <b>{Q1['cyc_avg']}d</b> · 99 issues</div>
      <div class="targetline"><span class="tl">Target</span> &le;6d median · &le;9d average</div>
      <div class="infopanel ip-amber">The median sits just above the 6-day target while the average is comfortably
      inside the 9-day one — the quarter's only metric not fully in the green. Measured from first entry into
      <i>In Development</i> to resolution, in calendar days, excluding sub-tasks.</div>
      <div class="cardfill"></div><hr class="docsep">{doclink('cycle', 'Cycle Time — Team Guide')}</div>
  </div>
  <div style="margin-top:24px"></div>
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    {rlink('q1', '&#128208;', 'Q1 2026 Report in Confluence')}
    {quarterlink()}
    {rlink('dash', '&#128216;', 'How to read the dashboard')}
    {dashlink()}
  </div></div>
  <div class="fnote">Definition used: <code>project = EDW AND issuetype NOT IN (Sub-task, Epic) AND resolution = Done</code>
  over each month's resolution date, which excludes discarded work. Figures reconciled in September 2026 — the method
  and what changed are documented in Findings &amp; Retro.</div>
</section>
{scrum_tab(names=q1n, title="Sprint metrics — Q1 2026", sub="The seven sprints that closed inside the quarter, rebuilt from Jira.", intro=intro)}
<section class="panel" id="cmp">
  <div class="sectit">Comparatives</div>
  <div class="secsub">Q1 against the rest of the year, and against the quarters that follow it.</div>
  <div class="cmpcard"><div class="cmphead"><h3>Q1 month by month</h3></div>
   <div class="chartbox" style="height:300px"><canvas id="cQ1"></canvas></div>
   <div class="infopanel ip-green">All three months land inside the healthy range. January is the strongest, and the
   quarter closes almost exactly on its own average — the profile of a steady quarter rather than a ramp.</div>
  </div>
  <div class="sectit" style="font-size:20px">Quarter comparison</div>
  <div class="tscroll"><table class="exec">
   <thead><tr><th>Reference</th><th>Period</th><th>Devs</th><th>Closed</th><th>Avg/month</th><th>Unplanned</th><th>Status</th></tr></thead>
   <tbody>
    <tr><td>Q1 2026</td><td>Jan - Mar</td><td>4</td><td>{Q1['closed']}</td><td>{Q1['thr_avg']}</td><td>{Q1_UNP_PCT:.2f}%</td><td>baseline, reconciled</td></tr>
    <tr><td>Q2 2026</td><td>Apr - Jun</td><td>4 &rarr; 6</td><td>{Q2['closed']}</td><td>{Q2['thr_avg']}</td><td>{Q2['unp']}%</td><td>mixed quarter, not usable</td></tr>
    <tr><td>Q3 2026</td><td>Jul - Sep</td><td>5</td><td class="flat">in progress</td><td class="flat">—</td><td class="flat">—</td><td class="flat">closes in September</td></tr>
   </tbody>
  </table></div>
</section>
<section class="panel" id="act">
  <div class="sectit">Findings &amp; retro</div>
  <div class="secsub">What to take from the quarter, and from the correction.</div>
  <div class="insightbox"><div class="k">Quarter takeaway</div>
   <h2>Q1 was a stable quarter. The reason nobody could tell is that three different numbers were circulating for the same metric.</h2>
   <p>40 deliveries a month with an 8-item spread, unplanned work comfortably under target and cycle time close to it.
   As a baseline it holds — with the caveat that it describes a 4-developer team, which EDW no longer is.</p></div>
  <div class="act"><div class="pri p-grey"></div><div class="inner">
   <div class="atop"><h4>How these figures were reconciled</h4><span class="pill pill-grey">Method</span></div>
   <p>The Q1 report published in Confluence carried two different throughput figures: 41 items/month in its executive
   summary, and 100 closed / 33.3 per month (10 &rarr; 45 &rarr; 45) in its detail section. Neither could be reproduced
   from Jira under any filter definition — January returns between 32 and 51 in every variant tested. The 100 matches
   the Cycle Time population instead: {Q1_CYC_RECALC['n']} of the {Q1['closed']} items closed in Q1 ever entered
   <i>In Development</i>, and the Cycle Time section is built on 99 issues. The same denominator explains the unplanned
   figure: the published {Q1['unp']}% is 5 items over 102, where over {Q1['closed']} it is {Q1_UNP_PCT:.2f}%. Both sit
   under target, so that status is unchanged. The Confluence page now carries the corrected figures.</p>
   <div class="owner">Reconciled: <b>September 2026</b></div></div></div>
  <div class="act"><div class="pri p-red"></div><div class="inner">
   <div class="atop"><h4>Retire one of the two throughput filters</h4><span class="pill pill-red">Action</span></div>
   <p>The dashboard gadget reads <i>EDW – Throughput – Previous Month (Resolved)</i> (id 14345), which has no
   <code>resolution</code> clause and counts Won't Do items — Q1 gives 124. <i>EDW – Throughput – Last Month</i>
   (id 14344) restricts to <code>issuetype in (Bug, Story)</code> — Q1 gives 122. The clean definition gives 120.
   While all three exist, the same metric reports a different number depending on where it is read. Database Services
   has the identical duplicated pair (ids 15837 and 16212).</p>
   <div class="owner">For action by: <b>EDW + DS</b></div></div></div>
  <div class="act"><div class="pri p-amber"></div><div class="inner">
   <div class="atop"><h4>Decide what Cycle Time counts</h4><span class="pill pill-amber">Discuss</span></div>
   <p>The published {Q1['cyc_med']}d / {Q1['cyc_avg']}d and the recalculated {Q1_CYC_RECALC['med']}d /
   {Q1_CYC_RECALC['avg']}d come from the same data read two ways. The monthly reports use the second method, so until
   this is settled, Q1 is not strictly comparable to the months that follow it.</p>
   <div class="owner">For discussion with: <b>EDW</b></div></div></div>
  <div class="act"><div class="pri p-blue"></div><div class="inner">
   <div class="atop"><h4>Commit to something closer to what gets delivered</h4><span class="pill pill-blue">Discuss</span></div>
   <p>Five of the seven Q1 sprints closed above 110% of their day-1 commitment. Reading that as over-performance is
   tempting and wrong: it means the sprint is planned after it starts. It is mild here and severe by August, so Q1 is
   where the habit is visible without the noise.</p>
   <div class="owner">For discussion with: <b>EDW</b></div></div></div>
  <div class="act"><div class="pri p-grey"></div><div class="inner">
   <div class="atop"><h4>Fix the sprint naming</h4><span class="pill pill-grey">Follow-up</span></div>
   <p><i>EDW-Sprint 8-27</i> should be 8-26. Cheap to fix, and it is the same slip DS has with <i>16-27</i> — worth a
   shared naming convention rather than two separate corrections.</p>
   <div class="owner">For follow-up by: <b>EDW + DS</b></div></div></div>
  <div class="retro"><h4>Questions for the team</h4><ul>
   <li>Looking at Q1: if we had committed to what we actually finished, what would each sprint have looked like?</li>
   <li>Which of the three throughput numbers have we been quoting to stakeholders?</li>
   <li>R9.00-S5 delivered 111 points against a 26-48 range everywhere else. What happened in that sprint?</li>
  </ul></div>
</section>"""
    charts = f"""
const q1Ref={{id:'q1Ref',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 const yp=y.getPixelForValue({Q1['thr_avg']});ctx.save();ctx.strokeStyle=BLUED;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);
 ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle=BLUED;ctx.font='600 10px DM Sans';ctx.textAlign='right';ctx.fillText('Quarter average {Q1['thr_avg']}',right-4,yp-4);ctx.restore();}}}};
new Chart(document.getElementById('cQ1'),{{type:'bar',
 data:{{labels:['January','February','March'],datasets:[
  {{label:'Items closed',data:[{Q1['months'][0]},{Q1['months'][1]},{Q1['months'][2]}],backgroundColor:BLUE,borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:55,grid:{{color:gridc}},title:{{display:true,text:'Items closed'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[q1Ref]}});
{charts_scrum(only=q1n)}"""
    return html + _fill(FOOT).replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)



# ------------------------------------------------------------------ findings
# A finding is a rule over the series, not a paragraph.
#
# The Findings tab used to be prose written for one period. When the next period
# closed it kept describing the last one, and nothing told anybody -- the same
# failure as a hand-written sprint goal or a hand-written label: a human
# description standing in for generated content. It also could not be ported to a
# second team without carrying this team's conclusions with it.
#
# So each finding states a condition, and the report evaluates it. It appears when
# it becomes true, carries the period it FIRST became true in, and stops being
# shown when the team fixes the thing. The series is truncated at the period being
# rendered, so a frozen report for 9.05 shows what was true in 9.05, not what is
# true today.
#
# A rule that has stopped firing is kept and shown separately. It is the only
# evidence a team ever gets that something they changed worked.

def _rel_spill(k):
    """Points that left the sprint over every point the sprint ever held."""
    done = gone = 0.0
    for n in (RELEASES.get(k) or {}).get("sprints", []):
        sp = SPILL.get(n)
        if not sp:
            continue
        done += sp["done"][1]
        gone += sp["open"][1] + sp["out"][1]
    return (gone / (done + gone)) if (done + gone) else None


def _rel_scope(k):
    """Day-1 commitment against final scope, over the release's own sprints."""
    c = f = 0.0
    for n in (RELEASES.get(k) or {}).get("sprints", []):
        r = sp(n)
        if not r:
            continue
        c += r[5]; f += r[6]
    return (f / c) if c else None


def _pctf(x):
    return f"{100*x:.0f}%"


FINDINGS = [
 dict(id="spill", sev="p-red", label="Risk",
      title=lambda k: "A third of committed work never finishes in its sprint",
      test=lambda k: (_rel_spill(k) or 0) >= 0.30,
      why="Every sprint reads as complete because the work is taken out before the "
          "sprint closes, not because it was done. The burndown cannot show this and "
          "the commitment number cannot either.",
      ev=lambda k: f"Points that left the sprint over every point it held: "
                   f"<b>{_pctf(_rel_spill(k))}</b>.",
      q="Do we close at 100% because we commit to less, or because work leaves the "
        "sprint before anyone counts it?"),

 dict(id="unp", sev="p-amber", label="Action",
      title=lambda k: "Reactive work cannot be measured at all",
      test=lambda k: (RELEASES.get(k) or {}).get("unp_pct") is None,
      why="Planned against unplanned is the one metric a service team cannot do "
          "without, and it is dark. Publishing 0% would invent an improvement nobody "
          "earned, so the charts break the line instead.",
      ev=lambda k: f"No item in <b>{MONTH_LABEL.get(k, k)}</b> carries the Unplanned "
                   f"label or the Urgent Task type.",
      q="What would make the Unplanned label get applied on its own, without "
        "depending on somebody remembering?"),

 dict(id="scope", sev="p-amber", label="Action",
      title=lambda k: "Scope roughly doubles after day 1",
      test=lambda k: (_rel_scope(k) or 0) >= 1.7,
      why="For a service team some of this is unavoidable: urgent requests land "
          "mid-sprint and cannot be planned. The question the split answers is how "
          "much of it was genuinely unplannable.",
      ev=lambda k: f"Day-1 commitment grows <b>{_rel_scope(k):.2f}x</b> by the time "
                   f"the sprints in {MONTH_LABEL.get(k, k)} close.",
      q="How much capacity should we reserve for service load, and why is the "
        "plannable half not on the board on day 1?"),

 dict(id="tail", sev="p-amber", label="Action",
      title=lambda k: "The cycle-time tail is pulling away from the median",
      test=lambda k: bool((CYC.get(k) or {}).get("med")) and
                     (CYC[k]["avg"] / CYC[k]["med"]) >= 1.8,
      why="The middle of the work flows fine. A few items sit for weeks, and only the "
          "average sees them, which is why a target on the average alone fires for a "
          "reason nobody can act on.",
      ev=lambda k: f"Average <b>{CYC[k]['avg']:.2f}d</b> against a median of "
                   f"<b>{CYC[k]['med']:.2f}d</b> \u2014 ratio {CYC[k]['avg']/CYC[k]['med']:.2f}, "
                   f"longest item {CYC[k].get('mx', 0):.0f}d.",
      q="Which items are the long tail, and what were they waiting for?"),

 dict(id="nodev", sev="p-amber", label="Action",
      title=lambda k: "Work closes without ever entering development",
      test=lambda k: bool((CYC.get(k) or {}).get("base")) and
                     CYC[k]["nodev"] / CYC[k]["base"] >= 0.20,
      why="Either the work was genuinely trivial, or the board is not being moved. "
          "The two have very different consequences, and cycle time is computed over "
          "what is left either way.",
      ev=lambda k: f"<b>{CYC[k]['nodev']} of {CYC[k]['base']}</b> closed items "
                   f"({_pctf(CYC[k]['nodev']/CYC[k]['base'])}) recorded no transition into "
                   f"<i>In Development</i>, so cycle time is computed over the other "
                   f"{CYC[k]['n']}.",
      q="Of the items that closed without entering development, how many were real "
        "work that skipped the board?"),

 dict(id="discard", sev="p-amber", label="Action",
      title=lambda k: "A tenth of resolved work is discarded, not delivered",
      test=lambda k: bool((RELEASES.get(k) or {}).get("resolved")) and
                     RELEASES[k]["discarded"] / RELEASES[k]["resolved"] >= 0.10,
      why="Work that reaches the board and is then thrown away was refined, estimated "
          "and planned first. That cost is already spent by the time it is dropped.",
      ev=lambda k: f"<b>{RELEASES[k]['discarded']} of {RELEASES[k]['resolved']}</b> "
                   f"resolved items ended as Won\u2019t Do "
                   f"({_pctf(RELEASES[k]['discarded']/RELEASES[k]['resolved'])}).",
      q="What did we open this period that ended as Won\u2019t Do, and what was "
        "missing when it came in?"),

 dict(id="shrink", sev="p-blue", label="Discuss",
      title=lambda k: "The team is smaller than the baselines were set with",
      test=lambda k: _prev_rel(k) is not None and
                     (CAP.get(k) or [0,0,0,0])[3] < (CAP.get(_prev_rel(k)) or [0,0,0,0])[3],
      why="Every fixed baseline on these pages was set with a different team. This is "
          "why the status comes from the team\u2019s own expected range rather than from "
          "the distance to a number somebody wrote down once.",
      ev=lambda k: f"People closing work went from <b>{CAP[_prev_rel(k)][3]:.0f}</b> in "
                   f"{MONTH_LABEL.get(_prev_rel(k), _prev_rel(k))} to "
                   f"<b>{CAP[k][3]:.0f}</b> in {MONTH_LABEL.get(k, k)}.",
      q="With the team we have today, how many deliveries a period and how many "
        "points a sprint are a realistic commitment?"),
]


def _prev_rel(k):
    ks = sorted(RELEASES)
    i = ks.index(k) if k in ks else -1
    return ks[i-1] if i > 0 else None


def find_eval(mk):
    """Every rule over the series up to and including `mk`. Returns the ones firing
    at `mk` with the period they first became true in, and the ones that were true
    earlier and have since stopped."""
    series = [k for k in sorted(RELEASES) if k <= mk]
    firing, cleared = [], []
    for rule in FINDINGS:
        hits = []
        for k in series:
            try:
                hits.append(bool(rule["test"](k)))
            except Exception:
                hits.append(False)          # a rule can never break a page
        if not any(hits):
            continue
        if hits[-1]:
            run = 0
            for h in reversed(hits):
                if not h: break
                run += 1
            firing.append(dict(rule=rule, first=series[len(hits)-run], streak=run))
        else:
            last = max(i for i, h in enumerate(hits) if h)
            cleared.append(dict(rule=rule, last=series[last],
                                gone=series[last+1] if last+1 < len(series) else None))
    firing.sort(key=lambda r: (FIND_RANK_IX.get(r["rule"]["sev"], 9), -r["streak"]))
    return firing, cleared


FIND_RANK_IX = {c: i for i, (c, _l, _d) in enumerate(FIND_RANK)}


def findings_panel(mk):
    firing, cleared = find_eval(mk)
    lab = MONTH_LABEL.get(mk, mk)
    out = ['<section class="panel" id="act">',
           '<div class="sectit">Findings &amp; retro</div>',
           '<div class="secsub">Each finding below is a rule over the series, not a note '
           'written for this page. It appears when it becomes true, carries the '
           f'{PERIOD_WORD} it first became true in, and disappears when the team fixes it. '
           f'Evaluated as of {lab}, so this page says what was true then.</div>']

    if not firing:
        out.append('<div class="insightbox"><div class="k">Nothing is firing</div>'
                   '<h2>No rule is true for this ' + PERIOD_WORD + '.</h2>'
                   '<p>That is a result, not an empty page.</p></div>')
    for f in firing:
        r, k = f["rule"], mk
        streak = f["streak"]
        since = (f'first true in {MONTH_LABEL.get(f["first"], f["first"])}'
                 + (f' \u00b7 {streak} {PERIOD_WORD}s running' if streak > 1 else ''))
        out.append(
            f'<div class="act"><div class="pri {r["sev"]}"></div><div class="inner">'
            f'<div class="atop"><h4>{r["title"](k)}</h4>'
            f'<span class="pill pill-{r["sev"].split("-")[1]}">{r["label"]}</span></div>'
            f'<p>{r["why"]}</p>'
            f'<div class="owner" style="font-weight:400">{r["ev"](k)}</div>'
            f'<div class="owner">{since}</div></div></div>')

    if cleared:
        out.append('<div class="sectit" style="font-size:20px;margin-top:28px">Cleared</div>'
                   '<div class="secsub">Rules that were true earlier in the series and are '
                   'not any more. This is the only evidence a team gets that something it '
                   'changed worked.</div>')
        for c in cleared:
            r = c["rule"]
            tail = (f'true through {MONTH_LABEL.get(c["last"], c["last"])}'
                    + (f', gone by {MONTH_LABEL.get(c["gone"], c["gone"])}' if c["gone"] else ''))
            out.append(
                f'<div class="act"><div class="pri p-green"></div><div class="inner">'
                f'<div class="atop"><h4>{r["title"](c["last"])}</h4>'
                f'<span class="pill pill-green">Cleared</span></div>'
                f'<p>{r["why"]}</p><div class="owner">{tail}</div></div></div>')

    qs = [f["rule"]["q"] for f in firing]
    if qs:
        out.append('<div class="sectit" style="font-size:20px;margin-top:28px">For the '
                   'retrospective</div><div class="secsub">One question per finding above. '
                   'When a finding clears, its question stops being asked.</div>'
                   '<div class="retro"><h4>Questions for the team</h4><ul>'
                   + "".join(f'<li>{q}</li>' for q in qs) + '</ul></div>')
    out.append('</section>')
    return "\n".join(out)


# ---------------------------------------------------------------- index page
BADGE_LABEL = {"healthy": "Healthy", "warning": "Warning", "risk": "Risk",
               "open": "In progress"}
BADGE_BG    = {"healthy": ("var(--healthy-bg)", "var(--healthy-fg)"), "warning": ("var(--warning-bg)", "var(--warning-fg)"),
               "risk": ("var(--risk-bg)", "var(--risk-fg)"), "open": ("var(--grid)", "var(--pillfg)")}

def _card(href, short, year, title, badge, blurb, status=None):
    bg, fg = BADGE_BG.get(status, ("var(--warning-bg)", "var(--warning-fg)"))
    r = _review(href)
    if href in DATA.get("HISTORICAL", []):
        # closed before the sign-off register existed. Saying "pending" would imply
        # somebody still owes a signature on a period nobody can re-live.
        pend = ('<span class="badge" style="background:var(--pillbg);color:#6b7383" '
                'title="Published before the sign-off register existed">Historical record</span>')
    elif r.get("status") == "reviewed":
        pend = '<span class="badge" style="background:var(--healthy-bg);color:var(--healthy-fg)">Signed off</span>'
    else:
        pend = '<span class="badge" style="background:var(--grid);color:var(--pillfg)">Pending sign-off</span>' 
    return f'''<a class="rcard" href="2026/{href}">
<div class="mo"><span class="m">{short}</span><span class="y">{year}</span></div>
<div class="body"><h3>{title} <span class="badge" style="background:{bg};color:{fg}">{badge}</span>{pend}</h3>
<p>{blurb}</p></div>
<div class="arrow">&rarr;</div></a>
'''

def _live_core(mode):
    """The live script itself, with the mode switch in front of it. One file, two
    pages: the index card and the sprint page render from the same code so they
    cannot drift apart."""
    core = open(os.path.join(REPO, "assets", "live.core.html")).read()
    return f"<script>window.__LIVE_MODE__={json.dumps(mode)};</script>\n" + core


def _live_foot(mode):
    """The live script wrapped in the index's closing shell."""
    shell = _fill(open(os.path.join(REPO, "assets", "foot.shell.html")).read())
    return shell.replace("__LIVE__", _live_core(mode))


SHELLCSS = """
 /* The reports lay out at 1180 and these pages were at 880, so moving between
    them shifted the whole page. They carry the same strip too, which does not fit
    880 once it has both buttons on it. */
 .wrap{max-width:1180px}
 .crumb{font-size:12.5px;color:var(--hdr-sub);margin-bottom:12px}
 .crumb a{color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.35)}
 .crumb a:hover{border-color:#fff}
 .repnav{background:var(--card);border-bottom:1px solid var(--line)}
 .repnav .wrap{display:flex;align-items:center;gap:8px;padding-top:11px;padding-bottom:11px;flex-wrap:wrap}
 .repnav .ry{font-size:11px;font-weight:800;letter-spacing:.14em;color:var(--wf-muted);margin-right:2px}
 .rp{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.06em;padding:5px 13px;border-radius:999px;
     text-decoration:none;color:var(--wf-blue-d);background:var(--wf-blue-bg);transition:.15s}
 .rp:hover{background:var(--wf-blue-l);color:#fff}
 .rsep{width:1px;height:18px;background:var(--line);margin:0 5px}
 .rp.live{background:var(--wf-blue);color:#fff;display:inline-flex;align-items:center;gap:7px}
 .rp.live i{width:6px;height:6px;border-radius:50%;background:var(--card);display:block;flex:0 0 auto}
 .rp.live:hover{background:var(--wf-blue-d);color:#fff}
 .rp.live.on{background:var(--wf-blue-d);cursor:default}
 /* These were a 12.5px bare link pushed to the edge. They are the way off the
    page, so they are sized like the pills they sit next to. */
 .rgroup{margin-left:auto;display:flex;align-items:center;gap:8px;flex:0 0 auto}
 .rutil{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:700;
   padding:6px 14px;border-radius:999px;text-decoration:none;color:var(--wf-blue-d);
   background:var(--card);border:1px solid var(--line);white-space:nowrap;transition:.15s}
 .rutil:hover{border-color:var(--wf-blue-l);background:var(--wf-blue-bg)}
 .rutil.on{background:var(--wf-blue-d);border-color:var(--wf-blue-d);color:#fff;cursor:default}
 /* The strip is longer now that the active sprint is in it. On a phone it scrolls
    sideways instead of wrapping into three lines. */
 @media(max-width:700px){
  .repnav .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;flex-wrap:nowrap}
  .repnav .wrap::-webkit-scrollbar{display:none}
  .rp,.ry{flex:0 0 auto}
  .rgroup{margin-left:12px;padding-top:0}
 }
"""

# Only the pages built on the index shell need this: the report pages get the tab
# machinery from their own stylesheet.
SPRINTCSS = """
 .tabs{position:sticky;top:0;z-index:30;background:color-mix(in srgb, var(--bg) 92%, transparent);backdrop-filter:blur(10px);
   border-bottom:1px solid var(--line)}
 .tabs .wrap{display:flex;gap:4px}
 .tab{appearance:none;background:none;border:none;font-family:'DM Sans';font-weight:600;font-size:15px;
   color:var(--wf-muted);padding:17px 22px;cursor:pointer;position:relative;transition:color .2s}
 .tab:hover{color:var(--wf-ink)}
 .tab.active{color:var(--wf-blue)}
 .tab.active::after{content:"";position:absolute;left:14px;right:14px;bottom:-1px;height:3px;
   background:var(--wf-blue);border-radius:3px 3px 0 0}
 .panel{display:none;animation:fade .4s ease}
 .panel.active{display:block}
 @keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
 .sectit{font-weight:800;font-size:24px;color:var(--wf-blue-d);margin:6px 0 2px;letter-spacing:-.01em}
 .secsub{color:var(--wf-muted);font-size:14px;margin-bottom:20px}
 .cmpcard{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;
   box-shadow:var(--shadow);margin-bottom:18px}
 /* the live blocks carry their own rule above them; as the first thing in a card
    that line reads as a stray divider */
 .cardbody>.sprintsec:first-child{margin-top:0;padding-top:0;border-top:none}
 .gsrc{margin-top:10px;padding-top:9px;border-top:1px solid var(--line);font-size:12px;
   color:var(--wf-muted);line-height:1.5}
 .goalbox a{color:var(--wf-blue);font-weight:600;text-decoration:none;border-bottom:1px solid #bcdcec}
 .goalbox a:hover{border-color:var(--wf-blue)}
 #livehead .liverow{justify-content:flex-start;gap:10px}
 #livehead .activetag{vertical-align:middle}
 @media(max-width:700px){
  .tabs .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;gap:0}
  .tabs .wrap::-webkit-scrollbar{display:none}
  .tab{padding:14px 14px;font-size:14px;white-space:nowrap;flex:0 0 auto}
  .cmpcard{padding:16px}
  .sectit{font-size:20px}
 }
"""


def sprint_page():
    """The active sprint, laid out like the reports it feeds: same header, same
    tab strip, same cards. The index card is the five-second read; this is the
    page behind it, and it should not look like a different site."""
    head = _fill(open(os.path.join(REPO, "assets", "index.head.html")).read())
    # reuse the index stylesheet verbatim -- the live blocks are styled there, and
    # a second copy would drift
    _a = head.find("<style>") + len("<style>")
    _b = head.find("</style>")
    css = head[_a:_b]

    strip = repnav("live", root=True)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TKEY} &middot; Active sprint</title>
<style>{css}{SHELLCSS}{SPRINTCSS}</style></head>
<body>
{THEMEJS}
<header><div class="wrap">{PREFBTN}
<div class="crumb"><a href="index.html">{TSITE}</a> &rsaquo; Active sprint</div>
<div class="eyebrow">{TEAM["name"]} &middot; Live from Jira</div>
<h1>Active sprint</h1>
<div class="sub">Everything the reports know about the sprint running right now, rebuilt from Jira on
every refresh. It gets a verdict in the release report once it closes, not before.</div>
<div id="livehead" style="margin-top:22px"></div>
</div></header>
<div class="tabs"><div class="wrap">
 <button class="tab active" data-tab="prog">Progress</button>
 <button class="tab" data-tab="flow">Workflow</button>
 <button class="tab" data-tab="rel">Release</button>
</div></div>
{strip}
<main><div class="wrap">
<div id="livepanel"></div>
{fixlink()}</div></main>
<footer>{TSITE} &middot; {TEAM["name"]} &middot; {TEAM["org"]} &middot;
<a href="admin.html" style="color:inherit">what to fix in Jira</a></footer>
{_live_core("full")}
</body></html>"""


def admin_page():
    """The fix-list. Same shell as the index, different audience: the reports are
    for stakeholders, this is for whoever keeps Jira honest. Every item on it is
    fixed by editing Jira, which is where the name comes from -- it is not only
    about the board, and half of it is the backlog."""
    head = _fill(open(os.path.join(REPO, "assets", "index.head.html")).read())
    foot = _fill(open(os.path.join(REPO, "assets", "admin.foot.html")).read())
    head = head.replace(f"<title>{TSITE}</title>",
                        f"<title>{TKEY} &middot; What to fix in Jira</title>")
    head = head.replace(f'<div class="eyebrow">{TEAM["name"]}</div>',
                        f'<div class="eyebrow">{TEAM["name"]} &middot; Admin</div>')
    head = head.replace(f"<h1>{TSITE}</h1>", "<h1>What to fix in Jira</h1>")
    _i, _j = head.find('<div class="sub">'), head.find("</div></div></header>")
    head = head[:_i] + ('<div class="sub">Everything on this page is fixable by editing Jira. '
                        'It is kept away from the reports on purpose: the reports are for '
                        'stakeholders, this is the list of things somebody has to go and fix.</div>') + head[_j:]
    head = head.replace('<div id="livepanel"></div>', '<div id="adminpanel"></div>')
    # the strip, so this page can be left the same way every other page can
    head = head.replace("</style>", SHELLCSS + "</style>")
    head = head.replace(f'<div class="eyebrow">{TEAM["name"]} &middot; Admin</div>',
                        f'<div class="crumb"><a href="index.html">{TSITE}</a> '
                        '&rsaquo; What to fix in Jira</div>'
                        '<div class="eyebrow">Enterprise Data Warehouse &middot; Admin</div>')
    head = head.replace('<main><div class="wrap">', repnav("fix", root=True) + '\n<main><div class="wrap">')
    return head + foot


def fixlink():
    """The way into the fix-list. A status indicator, not a nav item: it carries the
    count, and it goes quiet when there is nothing to do. Only on the pages whoever
    keeps the board honest is already looking at."""
    return ('<a class="adminlink" id="fixlink" href="admin.html">'
            '<i class="fixdot"></i>'
            '<b>What to fix in Jira</b>'
            '<span class="fixn">Counting&hellip;</span>'
            '<span class="fixar">&rarr;</span></a>\n')


def index_page():
    head = _fill(open(os.path.join(REPO, "assets", "index.head.html")).read())
    foot = _live_foot("compact")
    idx  = DATA.get("INDEX", {})

    def card_for(href, meta, status=None, short=None, title=None, blurb=None):
        meta = meta or {}
        badge = BADGE_LABEL.get(status, meta.get("badge", "Warning")) if status else meta.get("badge", "")
        return _card(href, short or meta.get("short", ""), "2026",
                     title or meta.get("title", ""), badge,
                     blurb if blurb is not None else meta.get("blurb", ""), status)

    rel, months, quarters = [], [], []
    # the measured ones only: an unmeasured release has no figures to put in a
    # card, and a card with no figures is a claim that there was nothing to show
    for rk, r in sorted(((k, v) for k, v in (DATA.get("RELEASES") or {}).items()
                         if v.get("closed") is not None or v.get("open")),
                        reverse=True):
        href = r["slug"] + ".html"
        _ns = [n.split()[-1].split("-")[0] for n in r["sprints"]]
        sub = (f"Sprint{'s' if len(_ns) > 1 else ''} {', '.join(_ns[:-1]) + ' and ' + _ns[-1] if len(_ns) > 1 else _ns[0]}"
               f" · {r['start']} to {r['end']} · {r['closed']} closed, {r['per_sprint']} per sprint")
        rel.append((href, card_for(href, idx.get(href), "open" if r.get("open") else r.get("status"),
                                   short=r["short"], title=f"Release {rk} Performance Report",
                                   blurb=(idx.get(href) or {}).get("blurb") or sub)))
    for short, href in DATA.get("REPORTS", []):
        meta = idx.get(href)
        if short.startswith("Q"):
            quarters.append((href, card_for(href, meta)))
        elif meta:
            mk = next((k for k, v in DATA.get("MONTHS", {}).items() if v["slug"] + ".html" == href), None)
            st = DATA.get("MONTHS", {}).get(mk, {}).get("status") if mk else None
            months.append((href, card_for(href, meta, st)))

    months.sort(key=lambda t: t[0], reverse=True)
    quarters.sort(key=lambda t: t[0], reverse=True)

    out = head
    if rel:
        out += ('\n<div class="yeartag">2026 · Release Reports</div>\n'
                '<p style="font-size:13px;color:var(--wf-muted);margin:-6px 0 14px">'
                'One report per release, covering the sprints that fed it. This is the current series.</p>\n'
                + "".join(c for _, c in rel))
    if quarters:
        out += ('<div class="yeartag" style="margin-top:30px">2026 · Quarter Reports</div>\n'
                + "".join(c for _, c in quarters))
    # The count is filled in by the live script. Until it lands the link still
    # works and still says what it is; it just cannot say how much yet.
    out += fixlink()
    return out + foot


# ---------------------------------------------------------------- month close
def freeze_month():
    """A month whose sprints have all closed and whose last day has passed becomes
    history: it moves into frozen.json and is never recomputed again. This is what
    keeps a published number from quietly changing weeks later."""
    if not (CURRENT and CURRENT.get("complete")):
        return False
    mk = CURRENT["ym"].split("-")[1]
    if mk in _FROZEN_MONTHS:          # already history; nothing to do
        return False
    D = json.load(open(os.path.join(REPO, "data", "frozen.json")))
    D.setdefault("MONTHS", {})[mk] = CURRENT["month"]
    D.setdefault("SP_BY_MONTH", {})[mk] = CURRENT["month"]["sprints"]
    D.setdefault("MONTH_LABEL", {})[mk] = CURRENT["month"]["label"].split()[0]
    have = {r[0] for r in D.get("SPRINTS", [])} | {r[0] for r in D.get("SPRINTS_Q1", [])}
    D.setdefault("SPRINTS", []).extend([r for r in CURRENT["SPRINTS"] if r[0] not in have])
    D["SPRINTS"] = _ordered(D["SPRINTS"], D["SP_BY_MONTH"])
    for key in ("SPILL", "SPLIT", "TIS", "CAP", "CYC"):
        D.setdefault(key, {}).update(CURRENT[key])
    href = CURRENT["month"]["slug"] + ".html"
    D.setdefault("INDEX", {})[href] = {
        "short": CURRENT["month"]["short"],
        "title": f"{CURRENT['month']['label']} Performance Report",
        "badge": BADGE_LABEL.get(CURRENT["month"]["status"], "Warning"),
        "blurb": CURRENT["month"]["headline"]}
    entry = [CURRENT["month"]["short"], href]
    if entry not in D.get("REPORTS", []):
        q = next((i for i, r in enumerate(D["REPORTS"]) if r[0].startswith("Q")), len(D["REPORTS"]))
        D["REPORTS"].insert(q, entry)
    with open(os.path.join(REPO, "data", "frozen.json"), "w") as f:
        json.dump(D, f, indent=1, ensure_ascii=False)
    try:
        os.remove(os.path.join(REPO, "data", "current.json"))
    except OSError:
        pass
    print(f"froze {CURRENT['month']['label']} into frozen.json - it will not be recomputed again")
    return True


def quarter_ready():
    """Names a quarter whose three months are all frozen but that has no page yet."""
    D = json.load(open(os.path.join(REPO, "data", "frozen.json")))
    closed = set(D.get("QUARTERS_CLOSED", []))
    cap = D.get("CAP", {})
    for q, ms in (("Q1", ["01","02","03"]), ("Q2", ["04","05","06"]),
                  ("Q3", ["07","08","09"]), ("Q4", ["10","11","12"])):
        if q not in closed and all(m in cap for m in ms):
            return q
    return None


# ---------------------------------------------------------------- write
os.makedirs(f"{REPO}/2026", exist_ok=True)
# The monthly series is retired: reporting moved to the release calendar and a
# second measurement path was being maintained and run in CI for a closed series.
# The frozen month data stays -- the quarter pages are built from it -- but the
# pages are no longer generated, and the cleanup below removes the published ones.
if not DATA.get("RELEASES"):
    for mk, m in MONTHS.items():
        open(f"{REPO}/2026/{m['slug']}.html","w").write(add_tips2(month_page(mk)))
        print("wrote", m["slug"])
# The quarter pages are EDW's published baselines: hand-written historical records
# of how the Q1 figures were derived and why Q2 does not work as a baseline. A team
# without them in frozen.json simply does not get them, rather than getting EDW's.
if DATA.get("QUARTERS_CLOSED"):
    open(f"{REPO}/2026/2026-q1.html","w").write(add_tips2(q1_page()))
    print("wrote 2026-q1")
    open(f"{REPO}/2026/2026-q2-baseline.html","w").write(add_tips2(q2_page()))
    print("wrote 2026-q2-baseline")


# ---------------------------------------------------------------- releases
# Second pass. A release is the same kind of period as a month, so it renders
# through the same engine; what changes is the window, the span (a release runs
# two sprints, sometimes three) and what it compares itself against — its own
# series rather than the calendar quarters, which belong to the quarter pages.
# A release is rendered once it has been measured. Before that it is a window and
# a list of sprints -- a fact about the calendar, not a result -- and publishing it
# would state that the team delivered nothing. scripts/backfill.py computes the
# closed ones from Jira; the refresh job measures the open one. Either way a page
# appears when there is something true to put on it.
RELEASES = {k: v for k, v in (DATA.get("RELEASES") or {}).items()
            if v.get("closed") is not None or v.get("open")}
_UNMEASURED = sorted(set(DATA.get("RELEASES") or {}) - set(RELEASES))
if _UNMEASURED:
    print("not measured yet, so not rendered:", ", ".join(_UNMEASURED),
          "-- run scripts/backfill.py for these")
if RELEASES:
    MONTHS       = RELEASES
    CAP          = DATA["CAP_R"]
    CYC          = DATA["CYC_R"]
    SP_BY_MONTH  = DATA["SP_BY_RELEASE"]
    MONTH_LABEL  = DATA["RELEASE_LABEL"]
    PNORM        = {k: v["n_sprints"] for k, v in RELEASES.items()}
    PERIOD_WORD  = "release"

    MK_ALL  = sorted(RELEASES)
    MK_OPEN = next((k for k, v in RELEASES.items() if v.get("open")), None)
    MK_DONE = [k for k in MK_ALL if k != MK_OPEN]
    MK_L3, MK_P3 = MK_DONE[-3:], MK_DONE[-6:-3] or MK_DONE[:1]
    MK_LAST = MK_ALL[-1]
    MK_LABS = [MONTH_LABEL[k] for k in MK_DONE]
    BASE_KEYS = []
    CYC_ORDER = list(MK_DONE)
    _FROZEN_MONTHS = set(MK_DONE)
    _cyckey = lambda k: k
    _sidx = lambda k: MK_DONE.index(k) if k in MK_DONE else None

    # the release in progress, fresh from Jira, replaces its frozen placeholder
    if CURRENT_RELEASE:
        _rk = CURRENT_RELEASE["ym"]
        _m  = CURRENT_RELEASE["month"]
        if _rk in RELEASES:
            _keep = {k: RELEASES[_rk][k] for k in ("slug","label","short","sprints","n_sprints","weeks") if k in RELEASES[_rk]}
            RELEASES[_rk] = {**_m, **_keep, "open": not CURRENT_RELEASE.get("complete"),
                             "per_sprint": round(_m["closed"]/max(1,_keep.get("n_sprints",1)), 1)}
            CAP[_rk] = list(CURRENT_RELEASE["CAP"].values())[0]
            CYC[_rk] = list(CURRENT_RELEASE["CYC"].values())[0]
        _final_r = {n for ns in SP_BY_MONTH.values() for n in ns} - set(RELEASES[_rk]["sprints"])
        _have_r  = {r[0] for r in SPRINTS}
        SPRINTS[:] = [r for r in SPRINTS if r[0] not in {x[0] for x in CURRENT_RELEASE["SPRINTS"]}]
        SPRINTS.extend(CURRENT_RELEASE["SPRINTS"])
        SPRINTS[:] = _ordered(SPRINTS, SP_BY_MONTH)
        for _src, _dst in ((CURRENT_RELEASE["SPILL"], SPILL), (CURRENT_RELEASE["SPLIT"], SPLIT),
                           (CURRENT_RELEASE["TIS"], TIS), (CURRENT_RELEASE.get("GHOST") or {}, GHOST)):
            _dst.update(_src)
        MK_OPEN = _rk if RELEASES[_rk].get("open") else None
        MK_DONE = [k for k in MK_ALL if k != MK_OPEN]
        MK_L3, MK_P3 = MK_DONE[-3:], MK_DONE[-6:-3] or MK_DONE[:1]
        MK_LABS = [MONTH_LABEL[k] for k in MK_DONE]
        CYC_ORDER = list(MK_DONE)
        PNORM = {k: v.get("n_sprints", 1) for k, v in RELEASES.items()}

    _prev = MK_DONE[-1] if MK_DONE else MK_ALL[0]
    def _unp(k):
        v = RELEASES[k].get("unp_pct")
        return v if v is not None else 0
    REF1_LABEL, REF1_SHORT = MONTH_LABEL[_prev], MONTH_LABEL[_prev]
    REF2_LABEL, REF2_SHORT = "Last 3 releases", "the band"
    # subtitle wording
    globals()["REF2_PHRASE"] = "the band of the last three releases"
    Q1 = dict(thr_med=round(cl(_prev)), thr_avg=cl(_prev), unit="/sprint",
              unp=_unp(_prev), cyc_med=CYC[_prev]["med"], cyc_avg=CYC[_prev]["avg"],
              nodev=CYC[_prev]["nodev"])
    # The band needs closed releases to be a band. A team whose first release is
    # still open has none, and every figure derived from it is then absent rather
    # than zero -- the pages read that as "no comparison yet" and say so.
    _n3 = len(MK_L3)
    _b = band([cl(k) for k in MK_L3]) if _n3 else dict(lo=0, hi=0, mean=0, move=0,
                                                       consistency=None)
    _avg = lambda f, nd=2: (round(sum(f(k) for k in MK_L3)/_n3, nd) if _n3 else None)
    Q2 = dict(thr_med=round(_b["mean"]), thr_avg=_b["mean"], unit="/sprint",
              unp=_avg(_unp, 1),
              cyc_med=_avg(lambda k: CYC[k]["med"]),
              cyc_avg=_avg(lambda k: CYC[k]["avg"]),
              nodev=sum(CYC[k]["nodev"] for k in MK_L3),
              note=" — the band is the team's own range over the last three releases, per sprint.")
    CAP_Q1, CAP_Q2 = [_prev], list(MK_L3)

    # each release is read against the one before it, put on the same number of
    # sprints so a six-week release is not compared to a four-week one head-on
    _rank = ["healthy", "warning", "risk"]
    for _i, _k in enumerate(MK_ALL):
        _r = RELEASES[_k]
        _p = MK_ALL[_i-1] if _i else None
        _r["prev"] = MONTH_LABEL[_p] if _p else "—"
        _r["prev_closed"] = round(cl(_p) * _r["n_sprints"]) if _p else _r["closed"]
        _notes, _st = [], "healthy"
        if _r.get("unp_pct") is None:
            _notes.append("the Unplanned label was not applied, so reactive work cannot be measured")
            _st = "warning"
        elif _r["unp_pct"] >= 15:
            _notes.append(f"unplanned work at {_r['unp_pct']}% of everything closed"); _st = "risk"
        elif _r["unp_pct"] >= 10:
            _notes.append(f"unplanned work at {_r['unp_pct']}%")
            _st = max(_st, "warning", key=_rank.index)
        _cs = cyc_status(CYC[_k])
        if _cs != "healthy":
            _notes.append(f"cycle time median {CYC[_k]['med']:.1f}d and average {CYC[_k]['avg']:.1f}d")
            _st = max(_st, _cs, key=_rank.index)
        if _r["discarded"] and _r["resolved"] and 100*_r["discarded"]/_r["resolved"] >= 20:
            _notes.append(f"{_r['discarded']} of {_r['resolved']} resolved items were discarded, not delivered")
            _st = max(_st, "warning", key=_rank.index)
        _move = (f"{_r['closed']} items closed over {_r['n_sprints']} sprints, "
                 f"{_r['per_sprint']} per sprint against {round(cl(_p),1) if _p else _r['per_sprint']}"
                 f" in {_r['prev']}" if _p else f"{_r['closed']} items closed over {_r['n_sprints']} sprints")
        _r["status"] = _st
        _r["headline"] = _move + ((". " + _notes[0][0].upper() + _notes[0][1:] + ".") if _notes else ".")
        _r["unp_items"] = _r.get("unp_items") or []
        if _r.get("open") and _r.get("sprints_done") is None:
            # a release is counted in sprints, so say how many of its own are done.
            # The collector already answers this from Jira's own sprint states; the
            # fallback is every sprint of the release except the one running.
            _lm = (LIVE or {}).get("month") or {}
            _r["sprints_done"] = (_lm.get("sprints_done")
                                  if _lm.get("label") == _r.get("label")
                                     and _lm.get("sprints_done") is not None
                                  else sum(1 for n in _r["sprints"] if n != ACTIVE))
        if _r.get("open"):
            _a = dt.date.fromisoformat(_r["start"]); _b = dt.date.fromisoformat(_r["end"])
            _r["days"] = (_b - _a).days + 1
            _r["day"]  = max(1, min(_r["days"], (dt.date.today() - _a).days + 1))

    REPORTS = [[v["short"], v["slug"] + ".html"] for k, v in sorted(RELEASES.items())]
    REPORTS += [r for r in DATA["REPORTS"] if r[0].startswith("Q")]

    for rk, r in RELEASES.items():
        open(f"{REPO}/2026/{r['slug']}.html", "w").write(add_tips2(month_page(rk)))
        print("wrote", r["slug"], f"({r['n_sprints']} sprints, {r['closed']} closed)")

# A page for a period that never froze is left over from before reporting moved
# to releases: not linked from anywhere, and holding half a period of numbers.
# Anything the index still lists — including the hand-kept May page — is safe.
if RELEASES:
    _keep = {v["slug"] + ".html" for v in DATA.get("RELEASES", {}).values()}
    _keep |= {h for _, h in DATA.get("REPORTS", [])}
    _keep |= set(DATA.get("INDEX", {}).keys())
    for _f in sorted(os.listdir(f"{REPO}/2026")):
        if _f.endswith(".html") and _f not in _keep:
            os.remove(f"{REPO}/2026/{_f}")
            print("removed stale in-progress page:", _f)

# after the report pages: the sprint page carries the same report strip they do,
# and REPORTS is only complete once the releases have been built
open(f"{REPO}/admin.html","w").write(admin_page())
open(f"{REPO}/sprint.html","w").write(sprint_page())
print("wrote admin + sprint")

open(os.path.join(REPO, "index.html"), "w").write(index_page())
print("wrote index")

_froze = freeze_month()
_q = quarter_ready()
if _q:
    print(f"NOTE: {_q} now has all of its months frozen and no quarter page yet.")
