#!/usr/bin/env python3
"""
Builds the EDW Performance Report pages.

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
MK_LAST = MK_ALL[-1]
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
    """Averages over the given periods, on the comparable scale (see cl)."""
    n=len(keys)
    nz=lambda k: PNORM.get(k,1)
    it=sum(CAP[k][0]/nz(k) for k in keys); sp=sum(CAP[k][1]/nz(k) for k in keys)
    pt=sum(CAP[k][2]/nz(k) for k in keys); pe=sum(CAP[k][3] for k in keys)/n
    return dict(items=it/n, pts=pt/n, size=pt/sp, people=pe, per=(pt/n)/pe)

def band(vals):
    """Expected range from the series' own month-to-month movement (XmR)."""
    mr=[abs(vals[i]-vals[i-1]) for i in range(1,len(vals))]
    mrbar=sum(mr)/len(mr); mean=sum(vals)/len(vals); half=2.66*mrbar
    return dict(lo=max(0,mean-half), hi=mean+half, mean=mean, move=mrbar,
                consistency=100*mrbar/mean)

def trend(keys_now, keys_prev):
    a=sum(cl(k) for k in keys_now)/len(keys_now)
    b=sum(cl(k) for k in keys_prev)/len(keys_prev)
    return 100*(a/b-1)

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
 .chartbox.zoomable:hover{background:#f7fafd}
 .chartbox.zoomable::after{content:"Expand";position:absolute;top:6px;right:8px;font-size:10.5px;font-weight:700;
   letter-spacing:.08em;text-transform:uppercase;color:var(--wf-blue);background:#fff;border:1px solid var(--line);
   border-radius:999px;padding:3px 9px;opacity:0;transition:opacity .15s;pointer-events:none}
 .chartbox.zoomable:hover::after{opacity:1}
 .cmodal{position:fixed;inset:0;z-index:200;background:rgba(20,32,44,.68);display:none;
   align-items:center;justify-content:center;padding:28px}
 .cmodal.open{display:flex}
 .cmbox{background:#fff;border-radius:18px;width:min(1180px,100%);height:min(78vh,760px);
   display:flex;flex-direction:column;box-shadow:0 18px 60px rgba(0,0,0,.35);overflow:hidden}
 .cmhead{display:flex;align-items:center;gap:14px;padding:16px 20px;border-bottom:1px solid var(--line)}
 .cmhead h4{font-size:17px;font-weight:700;color:var(--wf-blue-d);flex:1;line-height:1.3}
 .cmclose{appearance:none;border:1px solid var(--line);background:#fff;border-radius:9px;width:34px;height:34px;
   font-size:19px;line-height:1;color:var(--wf-muted);cursor:pointer;flex-shrink:0}
 .cmclose:hover{background:#f4f6fa;color:var(--wf-ink)}
 .cmbody{flex:1;padding:18px 20px 22px;min-height:0}
 @media(max-width:760px){.cmodal{padding:12px}.cmbox{height:min(88vh,620px)}.chartbox.zoomable::after{display:none}}
"""

NAVCSS = """
 .crumb{font-size:12.5px;color:#cfe7f3;margin-bottom:12px}
 .crumb a{color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.35)}
 .crumb a:hover{border-color:#fff}
 .repnav{background:#fff;border-bottom:1px solid var(--line)}
 .repnav .wrap{display:flex;align-items:center;gap:8px;padding-top:11px;padding-bottom:11px;flex-wrap:wrap}
 .repnav .ry{font-size:11px;font-weight:800;letter-spacing:.14em;color:var(--wf-muted);margin-right:2px}
 .rp{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.06em;padding:5px 13px;border-radius:999px;
     text-decoration:none;color:var(--wf-blue-d);background:var(--wf-blue-bg);transition:.15s}
 .rp:hover{background:var(--wf-blue-l);color:#fff}
 .rp.on{background:var(--wf-blue-d);color:#fff;cursor:default}
 .rsep{width:1px;height:18px;background:var(--line);margin:0 5px}
 .rhome{margin-left:auto;font-size:12.5px;font-weight:600;color:var(--wf-blue);text-decoration:none;white-space:nowrap}
 .rhome:hover{text-decoration:underline}
 @media(max-width:640px){.rhome{margin-left:0;width:100%;padding-top:4px}}
"""

def repnav(current):
    out = []
    for code, href in REPORTS:
        if code == "Q1":
            out.append('<span class="rsep"></span>')
        if code == current:
            out.append(f'<span class="rp on">{code}</span>')
        else:
            out.append(f'<a class="rp" href="{href}">{code}</a>')
    return ('<div class="repnav"><div class="wrap"><span class="ry">2026</span>'
            + "".join(out)
            + '<a class="rhome" href="../index.html">&larr; All reports</a></div></div>')



def add_tips(html):
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
         "risk":("b-red","Risk","var(--risk)")}

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
    """12-point sparkline, de-emphasised history with the current period in the accent."""
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
        dot = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{col}" stroke="#fff" stroke-width="2"/>'
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-hidden="true">'
            f'<path d="{d}" fill="none" stroke="#c3cdda" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
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
        keys += f'<span><i class="tisdot" style="background:{STCOL[st]}"></i>{st} <b>{med:.1f}d</b> <i style="font-style:normal;color:#9aa6b8">({n} items)</i></span>'
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
                 % (pct, STCOL.get(st, "#c3cdda"), (f"{med:.1f}d" if pct > 11 else "")))
        keys += ('<span><i class="tisdot" style="background:%s"></i>%s <b>%.1fd</b> '
                 '<i style="font-style:normal;color:#9aa6b8">(%d items)</i></span>'
                 % (STCOL.get(st, "#c3cdda"), st, med, n))
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
                  % (json.dumps(st), json.dumps(vals), STCOL.get(st, "#c3cdda")))
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
        col = STCOL.get(st, "#c3cdda")
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
    dev = abs(closed - Q1["thr_med"]) / Q1["thr_med"] * 100
    return "healthy" if dev <= 15 else ("warning" if dev <= 30 else "risk")

REVCSS = """
 .pillrow{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
 .statuspill{margin-top:0}
 .revchip{display:inline-flex;align-items:center;gap:8px;padding:8px 15px;border-radius:999px;
          font-weight:700;font-size:13.5px;letter-spacing:.01em;line-height:1}
 .revchip .ic{font-size:13px;line-height:1}
 .revchip.pend{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.34);color:#e9f4fa}
 .revchip.ok{background:rgba(126,217,181,.20);border:1px solid rgba(126,217,181,.55);color:#d6f5e8}
 .revnote{font-size:12.5px;color:var(--wf-muted);margin:-6px 0 18px}
 @media(max-width:600px){.revchip{font-size:12.5px;padding:7px 12px}}
"""

def review_chip(code):
    """Amber-free, header-safe chip. Pending until a human signs the page off."""
    slug = dict(REPORTS).get(code, "")
    if slug in DATA.get("HISTORICAL", []):
        return ('<span class="revchip" style="background:#f1f3f7;color:#6b7383">'
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
    # who it is still waiting on, when the register could be read
    wait = r.get("waiting_on") or []
    tail = (" · waiting on " + " and ".join(wait)) if wait else ""
    url  = r.get("url")
    chip = ('<span class="revchip pend"><span class="ic">&#9679;</span> '
            f'Generated from Jira · pending sign-off{tail}</span>')
    return f'<a href="{url}" style="text-decoration:none" title="Sign-off register in Confluence">{chip}</a>' if url else chip


def head(title, sub, pill, status, current=None):
    _,_,col = BADGE[status]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EDW · {title}</title>
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
 .nodata{{background:#f4f6fa;border:1px dashed #c3cdda;border-radius:12px;padding:18px;text-align:center;color:var(--wf-muted)}}
 .nodata .big{{font-size:26px;font-weight:800;color:#8b95a8;display:block;margin-bottom:4px}}
 .fnote{{font-size:12.5px;color:var(--wf-muted);border-left:3px solid var(--warning);padding-left:12px;margin-top:14px}}
{NAVCSS}{RESPCSS}{ZOOMCSS}{TIPCSS}{REVCSS}
</style></head>
<body>
<header><div class="wrap"><div class="crumb"><a href="../index.html">EDW Performance Reports</a> &rsaquo; {title}</div><div class="eyebrow">Enterprise Data Warehouse · Flow &amp; Sprint Metrics</div>
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
<footer>EDW Performance Reports · Enterprise Data Warehouse · Wellfit</footer>
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
document.querySelectorAll('.repnav a.rp').forEach(a=>{a.addEventListener('click',e=>{
 const t=currentTab(); if(t){e.preventDefault();location.href=a.getAttribute('href')+'#t='+t;}});});
(function(){var h=(location.hash||'').replace(/^#/,'').replace(/^t=/,'');if(h&&!showTab(h,false)){var f=document.querySelector('.tab');if(f)showTab(f.dataset.tab,false);}window.scrollTo(0,0);})();
Chart.defaults.font.family="'DM Sans', sans-serif";Chart.defaults.font.size=11;Chart.defaults.color='#626c84';
Chart.defaults.maintainAspectRatio=false;
const BLUE='#007CBC',BLUED='#005f91',BLUEL='#65B2D5',GREEN='#4FA800',AMBER='#ED7D31',RED='#d64550',GREY='#c3cdda';
const gridc='#eef2f8';
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
        short = c["sprint"].replace("EDW-Sprint ", "S")
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

def series_block(heading=True):
    """Historical, series-wide Scrum view. Lives in Comparatives on monthly pages."""
    closed = [r[7] for r in SPRINTS if r[0] != ACTIVE]
    avg5 = round(sum(closed[-5:])/5, 1)
    b  = band([cl(k) for k in MK_L3])
    b0 = band([cl(k) for k in BASE_KEYS]) if BASE_KEYS else b
    ss = spill_series([r[0] for r in SPRINTS])
    tr = trend(MK_L3, MK_P3)
    now  = sum(cl(k) for k in MK_L3)/len(MK_L3)
    prev = sum(cl(k) for k in MK_P3)/len(MK_P3)
    pplnow  = sum(CAP[k][3] for k in MK_L3)/len(MK_L3)
    pplprev = sum(CAP[k][3] for k in MK_P3)/len(MK_P3)
    head = ('<div class="sectit" style="font-size:20px;margin-top:30px">Sprint series — full history</div>'
            '<div class="secsub">Every sprint of 2026 on the board, so the month can be read against the trend.</div>'
            if heading else "")
    return f"""
 {head}
 <div class="insightbox" style="margin-bottom:24px"><div class="k">What the burndowns show</div>
  <h2>Scope roughly doubles mid-sprint, and most of what comes in was not reactive work.</h2>
  <p>EDW runs ScrumBan because it is a service team: urgent requests land mid-sprint and cannot be planned, which is exactly what Planned vs Unplanned exists to measure. So scope growth is expected here. The question is how much of it is genuinely unplannable. In the sprints where the <i>Unplanned</i> label was still being applied, reactive work accounts for <span class="stat">8% to 58%</span> of everything added after day 1, and in most of them it sits near the low end. The remainder is feature, QA and dashboard work — the kind that could have been on the board from the start.</p>
 </div>
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
 <div class="cmpcard">
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
    <div class="line" style="border-color:var(--wf-blue)"><span class="vs-tag">Trend {tr:+.0f}%</span><br>Average of the last three months against the three before them: {now:.0f} vs {prev:.0f} items. Team went from {pplprev:.1f} to {pplnow:.1f} people over the same stretch, so read the two together.</div>
    <div class="line" style="border-color:var(--healthy)"><span class="vs-tag">Expected range {b['lo']:.0f} - {b['hi']:.0f}</span><br>Built from the team's own month-to-month movement, not from a target. A month outside it means something changed; a month inside is normal variation.</div>
    <div class="line" style="border-color:var(--warning)"><span class="vs-tag">Consistency {b['consistency']:.0f}%</span><br>Throughput moves <b>{b['move']:.1f} items</b> from one month to the next on average, {b['consistency']:.0f}% of the level. Earlier in the year, on the 4-person team, that figure was {b0['consistency']:.0f}%.</div>
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
    <div class="line" style="border-color:var(--warning)"><span class="vs-tag">{ss['out_share']:.0f}% of it is removed, not carried</span><br>EDW takes work <i>out</i> of the sprint before closing it rather than letting it show as incomplete. That is why every sprint reads 100% complete — the sprint empties before it closes.</div>
    <div class="line" style="border-color:var(--wf-blue)"><span class="vs-tag">Read it against the commitment, not the burndown</span><br>A sprint that commits to 45 points, grows to 117, closes 69 and drops 48 has not delivered 100% of anything. The honest pair is day-1 commitment and spillover rate, side by side.</div>
   </div>
  </div>
  {change_note("spillover")}
  <div class="infopanel ip-amber">There is no sprint goal recorded on any of these sprints, so spillover cannot be read against what the sprint set out to achieve — only against the points. Recording a goal is what would make the difference between "we dropped 48 points" and "we dropped 48 points and still got there".</div>
 </div>
 {recv_card()}
 <div class="sectit" style="font-size:20px;margin-top:22px">Committed vs Completed — full series</div>
 <div class="secsub">Every sprint on the board this year.</div>
 {sprint_table([r[0] for r in SPRINTS])}
 <div class="fnote">Carry-over between sprints is close to zero, which at first looks like exceptional planning. The added column explains it: little carries over because little is committed up front — the sprint is filled in as it runs. For a service team part of that is unavoidable, but the reactive split shows most of the filling is plannable work. Two separate conversations for the retro: how much service load to reserve capacity for, and why plannable work is not on the board on day 1.</div>
"""

def charts_scrum(mk=None, only=None):
    names = json.dumps([r[0].replace("EDW-Sprint ","S") for r in SPRINTS])
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
 data:{{labels:{json.dumps([n.replace('EDW-Sprint ','S') for n in sl_names])},datasets:[
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
        cols = json.dumps(['#007CBC' if l==cur else '#c3cdda' for l in labs])
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
        _lb = json.dumps([n.replace("EDW-Sprint ","S").replace("DS-Sprint ","S") for n,_ in ss2["rows"]])
        _rt = json.dumps([round(r["rate"],1) for _,r in ss2["rows"]])
        _cl = json.dumps(["#d64550" if r["rate"]>=50 else ("#ED7D31" if r["rate"]>=33 else "#65B2D5") for _,r in ss2["rows"]])
        js += f"""
const spillRef={{id:'spillRef',afterDraw(c){{const{{ctx,chartArea:{{left,right}},scales:{{y}}}}=c;
 const yp=y.getPixelForValue({ss2['rate']:.1f});ctx.save();ctx.strokeStyle='#626c84';ctx.lineWidth=1.5;ctx.setLineDash([5,4]);
 ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle='#626c84';ctx.font='600 10px DM Sans';ctx.textAlign='right';
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
            _fl = json.dumps([n.replace("EDW-Sprint ", "S") for n, _ in _flow])
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
  {{label:'Ideal from day-1 commitment',data:{ideal},borderColor:'#c3cdda',borderDash:[5,4],pointRadius:0,borderWidth:2,fill:false}}{gh}]}},
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
    dev_base = (m["closed"] - Q1["thr_med"]*SHARE) / (Q1["thr_med"]*SHARE) * 100
    dev_q2   = (m["closed"] - Q2["thr_med"]*SHARE) / (Q2["thr_med"]*SHARE) * 100
    dev_prev = (m["closed"] - m["prev_closed"]*SHARE) / (m["prev_closed"]*SHARE) * 100
    types = " · ".join(f"{n} {t}" for t,n in m["types"])

    # unplanned card
    if m["unplanned"] is None:
        unp_card = f"""<div class="card">
      <div class="ghead"><span class="gname">Planned vs Unplanned</span><span class="badge" style="background:#eef1f6;color:#69727d"><span class="d" style="background:#8b95a8"></span>No data</span></div>
      <div class="nodata" style="margin:10px 0"><span class="big">—</span>0 items labeled <i>Unplanned</i> {"so far this " + PERIOD_WORD if m.get("open") else "in the whole " + PERIOD_WORD}</div>
      <div class="targetline"><span class="tl">Target</span> &le;5% · Warning 5-10% · Risk &gt;10%</div>
      <div class="infopanel ip-amber">Zero labels in a {PERIOD_WORD} of {m['closed']} deliveries does not mean zero reactive work: it means the labeling stopped being applied. Publishing 0% would invent an improvement the team did not have. The labeling follow-up has been open since the May retro.</div>
      <div class="cardfill"></div><hr class="docsep">
      <a class="doclink" href="{GUIDES['unp']}" target="_blank">Planned vs Unplanned — Team Guide</a></div>"""
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
      <div class="ctxline"><span>Q1 <b>{Q1['unp']}%</b> · Q2 <b>{Q2['unp']}%</b> · May <b>{MAY_UNP}%</b></span></div>
      <div class="infopanel {ip}"><a href="#" class="ip-link" data-goto="act">See the breakdown in Findings &amp; Retro &rarr;</a></div>
      <div class="cardfill"></div><hr class="docsep">
      <a class="doclink" href="{GUIDES['unp']}" target="_blank">Planned vs Unplanned — Team Guide</a></div>"""

    # WIP card - live only on the latest month
    if mk == MK_LAST:
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
      <a class="doclink" href="{GUIDES['wip']}" target="_blank">WIP — Team Guide</a></div>"""
    else:
        wip_card = f"""<div class="card wipcard">
      <div class="ghead"><span class="gname">Work In Progress</span><span class="badge" style="background:#eef1f6;color:#69727d"><span class="d" style="background:#8b95a8"></span>No data</span></div>
      <div class="nodata" style="margin:10px 0"><span class="big">—</span>historical snapshot not captured</div>
      <div class="infopanel ip-amber">WIP is a point-in-time reading, not a monthly aggregate. It was not captured at the close of {m['label'].split()[0]}, and Jira cannot rebuild it backwards without the Cumulative Flow Diagram. The current snapshot lives in the August report.</div>
      <div class="cardfill"></div><hr class="docsep">
      <a class="doclink" href="{GUIDES['wip']}" target="_blank">WIP — Team Guide</a></div>"""

    if m["unplanned"] is None:
        unp_row = (f'<td class="flat">no data</td><td class="flat">—</td><td>{Q1["unp"]}%</td>'
                   f'<td>{Q2["unp"]}%</td><td class="flat">—</td><td class="flat">—</td>')
    else:
        unp_row = (f'<td>{m["unp_pct"]:.2f}%</td><td class="flat">—</td><td>{Q1["unp"]}%</td><td>{Q2["unp"]}%</td>'
                   f'<td class="neg">+{m["unp_pct"]-Q1["unp"]:.1f} pp</td>'
                   f'<td class="{"pos" if m["unp_pct"]<Q2["unp"] else "neg"}">{m["unp_pct"]-Q2["unp"]:+.1f} pp</td>')

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
        pct_d = 100*m["discarded"]/m["resolved"]
        disc_note = f"""<div class="act"><div class="pri p-grey"></div><div class="inner">
     <div class="atop"><h4>Review the {m['discarded']} discarded items</h4><span class="pill pill-grey">Follow-up</span></div>
     <p>The official Throughput filter uses <i>resolved</i>, which mixes closed with discarded (Won't Do). This {PERIOD_WORD} that is {m['discarded']} of {m['resolved']} resolved ({pct_d:.0f}%), which is why the headline counts only the {m['closed']} closed. Worth looking at in the retro at what was opened and then dropped — it usually signals work that came in without enough definition.</p>
     <div class="owner">Follow-up by: <b>EDW</b></div></div></div>"""

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
    _ck     = [k for k in CYC_ORDER]
    _cyc_l  = json.dumps([REF1_SHORT, REF2_SHORT] + [MONTH_LABEL.get(k, k) for k in _ck])
    _cyc_m  = json.dumps([Q1["cyc_med"], Q2["cyc_med"]] + [CYC[k]["med"] for k in _ck])
    _cyc_a  = json.dumps([Q1["cyc_avg"], Q2["cyc_avg"]] + [CYC[k]["avg"] for k in _ck])
    _cyc_max = max([Q1["cyc_avg"], Q2["cyc_avg"]] + [CYC[k]["avg"] for k in _ck] + [1]) * 1.2

    html = head(f"{m['label']} Performance Report",
                f"Flow and sprint metrics for the {PERIOD_WORD}, against {m['prev']} and {globals().get('REF2_PHRASE', REF2_LABEL)}.",
                f"Flow Health: {BADGE[m['status']][1].upper()} — {m['headline']}", m["status"], m["short"])

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
      {sb_rows([("Items closed", f"{cm['items']:.0f}", 100*(cm['items']/(cq1['items']*SHARE)-1), 100*(cm['items']/(cq2['items']*SHARE)-1), False),
                ("Story points", f"{cm['pts']:.0f}", 100*(cm['pts']/(cq1['pts']*SHARE)-1), 100*(cm['pts']/(cq2['pts']*SHARE)-1), False)])}
      <div class="ctxline"><span>Average item size <b>{cm['size']:.2f} pts</b> <i>({REF1_SHORT} {cq1['size']:.2f})</i></span>
        <span>Team <b>{cm['people']:.0f} active</b> <i>({REF1_SHORT} {cq1['people']:.1f})</i></span></div>
      <div class="spark-cap">Items closed · {MK_LABS[0]} to {MK_LABS[-1]}{" · this " + PERIOD_WORD + " is still running and is not plotted" if mk not in MK_DONE else ""}</div>
      {spark([cl(k) for k in MK_DONE], _sidx(mk))}
      <div class="infopanel {ip_thr}">On top of the {m['closed']} closed there were <b>{m['discarded']} discarded</b> (Won't Do), which are not deliveries.
        Items are {"" if OPEN else "up "}{100*(cm['items']/(cq1['items']*SHARE)-1):+.0f}% on {REF1_SHORT} while points are {"" if OPEN else "up "}{100*(cm['pts']/(cq1['pts']*SHARE)-1):+.0f}%{" at the same point in the month" if OPEN else " — the team is larger and the items are smaller"}.
        <a href="#" class="ip-link" data-goto="cmp">Trend and expected range in Comparatives &rarr;</a></div>
      <div class="cardfill"></div><hr class="docsep">
      <a class="doclink" href="{GUIDES['thr']}" target="_blank">Throughput — Team Guide</a>
    </div>
    <div class="card">
      <div class="ghead"><span class="gname">Cycle Time</span>{badge(cyc_st)}</div>
      <div class="bignum {col_cyc}">{c['med']:.2f}<span class="unit">d median</span></div>
      <div class="secondary">{c['n']} issues measured · longest {c['mx']:.0f}d</div>
      <div class="targetline"><span class="tl">Target</span> &le;6d median · &le;9d average</div>
      {sb_rows([("Median", f"{c['med']:.1f}d", 100*(c['med']-Q1['cyc_med'])/Q1['cyc_med'], 100*(c['med']-Q2['cyc_med'])/Q2['cyc_med'], True),
                ("Average", f"{c['avg']:.1f}d", 100*(c['avg']-Q1['cyc_avg'])/Q1['cyc_avg'], 100*(c['avg']-Q2['cyc_avg'])/Q2['cyc_avg'], True)])}
      <div class="ctxline"><span>Measured on <b>{c['n']} of {c['base']}</b> closed items <i>({100*c['n']/c['base']:.0f}% of the {PERIOD_WORD})</i></span></div>
      <div class="spark-cap">Median cycle time · {_plabel(CYC_ORDER[0]) if CYC_ORDER else ""} to {_plabel(CYC_ORDER[-1]) if CYC_ORDER else ""}</div>
      {spark([CYC[k]['med'] for k in CYC_ORDER], CYC_ORDER.index(_cyckey(mk)) if _cyckey(mk) in CYC_ORDER else None, col="#4FA800")}
      <div class="infopanel ip-green">Median and average both within target. The gap between {c['med']:.1f}d and {c['avg']:.1f}d comes from a few long tickets — the longest this month took {c['mx']:.0f} days.</div>
      <div class="cardfill"></div><hr class="docsep">
      <a class="doclink" href="{GUIDES['cycle']}" target="_blank">Cycle Time — Team Guide</a>
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
          <div class="ml-row"><span class="ml-sw" style="background:#c3cdda"></span><span class="ml-nm">Won't Do</span><span class="ml-val">{m['discarded']}</span></div>
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
      <tr><td>Cycle Time (median)</td><td>{c['med']:.2f}d</td><td class="flat">—</td><td>{Q1['cyc_med']}d</td><td>{Q2['cyc_med']}d</td><td class="{'neg' if c['med']>Q1['cyc_med'] else 'pos'}">{100*(c['med']-Q1['cyc_med'])/Q1['cyc_med']:+.1f}%</td><td class="{'neg' if c['med']>Q2['cyc_med'] else 'pos'}">{100*(c['med']-Q2['cyc_med'])/Q2['cyc_med']:+.1f}%</td></tr>
      <tr><td>Closed without entering development</td><td>{c['nodev']} ({nodev_pct:.0f}%)</td><td class="flat">—</td><td class="flat">—</td><td>{Q2['nodev']}</td><td class="flat">—</td><td class="flat">—</td></tr>
    </tbody>
  </table></div>
  <div class="fnote">Comparatives use the closed quarters of the year: Q1 and Q2. Q3 joins this table once September closes and its report is created. Q1's monthly detail is under review — the figure used here is the one published in Confluence.</div>
  {tis_flow_block(mk)}
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    <a class="rlink" href="{GUIDES['dash']}" target="_blank"><span class="ico">&#128216;</span> How to read the dashboard</a>
    <a class="rlink" href="{GUIDES['q1']}" target="_blank"><span class="ico">&#128208;</span> Q1 2026 Baseline</a>
    <a class="rlink" href="2026-q2-baseline.html"><span class="ico">&#128202;</span> Q2 2026 Report</a>
    <a class="rlink" href="https://wellfit.atlassian.net/jira/dashboards/11272" target="_blank"><span class="ico">&#128200;</span> EDW ScrumBan Dashboard</a>
  </div></div>
</section>

{scrum_tab(mk)}
<section class="panel" id="cmp">
  <div class="sectit">Comparatives</div>
  <div class="secsub">The full series from the baseline, so the trend shows and not just the month.</div>
  {_tis_card}
  <div class="cmpcard">
    <div class="cmphead"><h3><span class="st-dot" style="background:{BADGE[st_thr][2]};width:13px;height:13px"></span> Throughput</h3>{badge(st_thr)}</div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cThru"></canvas></div>
      <div class="readout">
        <div class="line" style="border-color:{BADGE[st_thr][2]}"><span class="vs-tag">vs {REF1_SHORT} ({Q1['thr_med']}{Q1.get('unit','/mo')})</span><br><b>{dev_base:+.1f}%</b> in items — but {100*(cm['per']/cq1['per']-1):+.0f}% once item size and team size are taken out. Most of the gap is a bigger team closing smaller items.</div>
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
  <div class="cmpcard">
    <div class="cmphead"><h3>Unplanned work</h3></div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cUnp"></canvas></div>
      <div class="readout">
        <div class="line"><span class="vs-tag">The series</span><br>Q1 {Q1['unp']}% &rarr; Q2 {Q2['unp']}% &rarr; May 17.95% &rarr; June 6.76% &rarr; July 12.66% &rarr; August no data.</div>
        <div class="line" style="border-color:var(--warning)"><span class="vs-tag">Careful</span><br>August's break is not a drop to zero, it is missing labeling. The line is interrupted on purpose.</div>
      </div>
    </div>
  </div>
  {series_block()}
</section>
<section class="panel" id="act">
  <div class="sectit">Findings &amp; retro</div>
  <div class="secsub">What the data shows, as input for the team's conversation.</div>
  <div class="insightbox"><div class="k">Observation of the month</div>
   <h2>{m['headline']}</h2>
   <p>The references we measure against — {Q1['thr_med']} deliveries a month, {VEL_BASE} points a sprint, WIP of 12/6/18 — were set with a 4-dev team in Q1. Since then Harisha and Shruti joined and Dipika left. Comparing against those figures says more about the baseline than about the team.</p>
  </div>
  {obs_block}
  <div class="sectit" style="font-size:20px;margin-top:28px">Directions to explore</div>
  <div class="secsub">Ideas to validate, adapt or set aside depending on the real context.</div>
  <div class="act"><div class="pri p-blue"></div><div class="inner">
   <div class="atop"><h4>Recalculate the baselines with the current team</h4><span class="pill pill-blue">Discuss</span></div>
   <p>Throughput and Velocity have been out of range for months, and WIP has already been recalculated to 5 devs. The guide asks for a quarterly review; the Q2 report in this series proposes the new starting point.</p>
   <div class="owner">For discussion with: <b>EDW</b></div></div></div>
  <div class="act"><div class="pri p-blue"></div><div class="inner">
   <div class="atop"><h4>Look at the sustained 100% completion</h4><span class="pill pill-blue">Discuss</span></div>
   <p>Five sprints in a row closing everything committed, with no spillover. It could be conservative planning, or tickets closed right at the sprint edge. The team is the one who knows which, and the answer changes how reliable Velocity is for planning.</p>
   <div class="owner">For discussion with: <b>EDW</b></div></div></div>
  <div class="act"><div class="pri p-amber"></div><div class="inner">
   <div class="atop"><h4>Bring back the Unplanned label</h4><span class="pill pill-amber">Action</span></div>
   <p>Without it there is no predictability metric. It is the same follow-up left open in the May retro, and in August it cut the series entirely.</p>
   <div class="owner">Follow-up by: <b>EDW</b></div></div></div>
  {disc_note}
  <div class="act"><div class="pri p-amber"></div><div class="inner">
   <div class="atop"><h4>{c['nodev']} items closed without entering development</h4><span class="pill pill-amber">Review</span></div>
   <p>Of the {c['base']} items closed this {PERIOD_WORD}, {c['nodev']} ({nodev_pct:.0f}%) never recorded a transition into <i>In Development</i>: they went from backlog or the previous column straight to closed. Those tickets have no Cycle Time, so the metric is computed over the remaining {c['n']}. {_nodev_ref} It may be genuinely trivial work, or tickets closed without going through the flow — worth telling apart, because it changes how much Cycle Time really represents the month's work.</p>
   <div class="owner">To review with: <b>EDW</b></div></div></div>
  <div class="sectit" style="font-size:20px;margin-top:28px">For the retrospective</div>
  <div class="retro"><h4>Questions for the team</h4><ul>
   <li>Do we close at 100% because we commit to less, or because we close tickets to make the sprint cut-off?</li>
   <li>With 5 devs today, how many deliveries a month and how many points a sprint are a realistic commitment?</li>
   <li>What did we open this month that ended as Won't Do, and what was missing when it came in?</li>
   <li>What would make the <i>Unplanned</i> label get applied on its own, without depending on someone remembering?</li>
  </ul></div>
</section>"""

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
 data:{{labels:['Q1','Q2','May','Jun','Jul','Aug'],datasets:[{{data:[{Q1['unp']},{Q2['unp']},{MAY_UNP},6.76,12.66,null],
  borderColor:BLUED,backgroundColor:BLUED,tension:.25,pointRadius:6,borderWidth:3,spanGaps:false,
  pointBackgroundColor:[GREEN,AMBER,RED,AMBER,RED,GREY]}}]}},
 options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>c.raw==null?' no data':` ${{c.raw}}% unplanned`}}}}}},
  scales:{{y:{{beginAtZero:true,max:20,grid:{{color:gridc}},ticks:{{callback:v=>v+'%'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[bands]}});
{charts_scrum(mk)}""" + _tis_js
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)

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
      <div class="cardfill"></div><hr class="docsep"><a class="doclink" href="{GUIDES['thr']}" target="_blank">Throughput — Team Guide</a></div>
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
      <div class="cardfill"></div><hr class="docsep"><a class="doclink" href="{GUIDES['unp']}" target="_blank">Planned vs Unplanned — Team Guide</a></div>
  </div>
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    <a class="rlink" href="{GUIDES['dash']}" target="_blank"><span class="ico">&#128216;</span> How to read the dashboard</a>
    <a class="rlink" href="{GUIDES['q1']}" target="_blank"><span class="ico">&#128208;</span> Q1 2026 Baseline</a>
    <a class="rlink" href="{GUIDES['thr']}" target="_blank"><span class="ico">&#128202;</span> Throughput — Team Guide</a>
    <a class="rlink" href="https://wellfit.atlassian.net/jira/dashboards/11272" target="_blank"><span class="ico">&#128200;</span> EDW ScrumBan Dashboard</a>
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
 <div class="act"><div class="pri p-green"></div><div class="inner">
  <div class="atop"><h4>Adopt Jun-Aug as the working baseline</h4><span class="pill pill-green">Proposal</span></div>
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
   backgroundColor:['#c3cdda','#c3cdda','#c3cdda','#65B2D5','#65B2D5','#007CBC','#007CBC','#007CBC'],borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:110,grid:{{color:gridc}},title:{{display:true,text:'Items closed'}}}},x:{{grid:{{display:false}}}}}}}}}});
{charts_scrum()}"""
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)

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
      <div class="cardfill"></div><hr class="docsep"><a class="doclink" href="{GUIDES['thr']}" target="_blank">Throughput — Team Guide</a></div>
    <div class="card"><div class="ghead"><span class="gname">Planned vs Unplanned</span>{badge('healthy')}</div>
      <div class="bignum num-green">{Q1_UNP_PCT:.2f}<span class="unit">%</span></div>
      <div class="secondary">{Q1_UNP_N} of {Q1['closed']} closed · Jan 1 · Feb 2 · Mar 2</div>
      <div class="targetline"><span class="tl">Target</span> &le;5%</div>
      <div class="infopanel ip-green">Comfortably inside target and the most stable metric of the quarter: never more
      than 2 unplanned items in a month. This is the reference the later months are measured against.</div>
      <div class="cardfill"></div><hr class="docsep"><a class="doclink" href="{GUIDES['unp']}" target="_blank">Planned vs Unplanned — Team Guide</a></div>
    <div class="card"><div class="ghead"><span class="gname">Cycle Time</span>{badge('warning')}</div>
      <div class="bignum num-amber">{Q1['cyc_med']}<span class="unit">d median</span></div>
      <div class="secondary">Average <b>{Q1['cyc_avg']}d</b> · 99 issues</div>
      <div class="targetline"><span class="tl">Target</span> &le;6d median · &le;9d average</div>
      <div class="infopanel ip-amber">The median sits just above the 6-day target while the average is comfortably
      inside the 9-day one — the quarter's only metric not fully in the green. Measured from first entry into
      <i>In Development</i> to resolution, in calendar days, excluding sub-tasks.</div>
      <div class="cardfill"></div><hr class="docsep"><a class="doclink" href="{GUIDES['cycle']}" target="_blank">Cycle Time — Team Guide</a></div>
  </div>
  <div style="margin-top:24px"></div>
  <div class="reslinks"><div class="rt">Resources</div><div class="rgrid">
    <a class="rlink" href="{GUIDES['q1']}" target="_blank"><span class="ico">&#128208;</span> Q1 2026 Report in Confluence</a>
    <a class="rlink" href="2026-q2-baseline.html"><span class="ico">&#128202;</span> Q2 2026 Report</a>
    <a class="rlink" href="{GUIDES['dash']}" target="_blank"><span class="ico">&#128216;</span> How to read the dashboard</a>
    <a class="rlink" href="https://wellfit.atlassian.net/jira/dashboards/11272" target="_blank"><span class="ico">&#128200;</span> EDW ScrumBan Dashboard</a>
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
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + RESIZEJS + TIPJS)


# ---------------------------------------------------------------- index page
BADGE_LABEL = {"healthy": "Healthy", "warning": "Warning", "risk": "Risk"}
BADGE_BG    = {"healthy": ("#e6f6ef", "#1a7f5a"), "warning": ("#fdeee3", "#c0641f"),
               "risk": ("#fdeaea", "#b3261e")}

def _card(href, short, year, title, badge, blurb, status=None):
    bg, fg = BADGE_BG.get(status, ("#fdeee3", "#c0641f"))
    r = _review(href)
    if href in DATA.get("HISTORICAL", []):
        # closed before the sign-off register existed. Saying "pending" would imply
        # somebody still owes a signature on a period nobody can re-live.
        pend = ('<span class="badge" style="background:#f1f3f7;color:#6b7383" '
                'title="Published before the sign-off register existed">Historical record</span>')
    elif r.get("status") == "reviewed":
        pend = '<span class="badge" style="background:#e3fcef;color:#1a6b45">Signed off</span>'
    else:
        pend = '<span class="badge" style="background:#eef2f8;color:#5a6577">Pending sign-off</span>' 
    return f'''<a class="rcard" href="2026/{href}">
<div class="mo"><span class="m">{short}</span><span class="y">{year}</span></div>
<div class="body"><h3>{title} <span class="badge" style="background:{bg};color:{fg}">{badge}</span>{pend}</h3>
<p>{blurb}</p></div>
<div class="arrow">&rarr;</div></a>
'''

def admin_page():
    """The board-hygiene page. Same shell as the index, different audience: this one
    is for whoever keeps Jira honest, so it is linked from the index rather than
    listed on it."""
    head = open(os.path.join(REPO, "assets", "index.head.html")).read()
    foot = open(os.path.join(REPO, "assets", "admin.foot.html")).read()
    head = head.replace("<title>EDW Performance Reports</title>",
                        "<title>EDW &middot; Board hygiene</title>")
    head = head.replace('<div class="eyebrow">Enterprise Data Warehouse</div>',
                        '<div class="eyebrow">Enterprise Data Warehouse &middot; Admin</div>')
    head = head.replace("<h1>EDW Performance Reports</h1>", "<h1>Board hygiene</h1>")
    _i, _j = head.find('<div class="sub">'), head.find("</div></div></header>")
    head = head[:_i] + ('<div class="sub">Everything on this page is fixable by editing Jira. '
                        'It is kept away from the reports on purpose: the reports are for '
                        'stakeholders, this is for whoever keeps the board honest.</div>') + head[_j:]
    head = head.replace('<div id="livepanel"></div>', '<div id="adminpanel"></div>')
    return head + foot


def index_page():
    head = open(os.path.join(REPO, "assets", "index.head.html")).read()
    foot = open(os.path.join(REPO, "assets", "index.foot.html")).read()
    idx  = DATA.get("INDEX", {})

    def card_for(href, meta, status=None, short=None, title=None, blurb=None):
        meta = meta or {}
        badge = BADGE_LABEL.get(status, meta.get("badge", "Warning")) if status else meta.get("badge", "")
        return _card(href, short or meta.get("short", ""), "2026",
                     title or meta.get("title", ""), badge,
                     blurb if blurb is not None else meta.get("blurb", ""), status)

    rel, months, quarters = [], [], []
    for rk, r in sorted(DATA.get("RELEASES", {}).items(), reverse=True):
        href = r["slug"] + ".html"
        _ns = [n.split()[-1].split("-")[0] for n in r["sprints"]]
        sub = (f"Sprint{'s' if len(_ns) > 1 else ''} {', '.join(_ns[:-1]) + ' and ' + _ns[-1] if len(_ns) > 1 else _ns[0]}"
               f" · {r['start']} to {r['end']} · {r['closed']} closed, {r['per_sprint']} per sprint")
        rel.append((href, card_for(href, idx.get(href), r.get("status"),
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
    out += ('<a class="adminlink" href="admin.html">&#9881;&#65039; Board hygiene '
            '&mdash; Definition of Ready, backlog health and field checks</a>\n')
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
        open(f"{REPO}/2026/{m['slug']}.html","w").write(add_tips(month_page(mk)))
        print("wrote", m["slug"])
open(f"{REPO}/admin.html","w").write(admin_page())
print("wrote admin")
open(f"{REPO}/2026/2026-q1.html","w").write(add_tips(q1_page()))
print("wrote 2026-q1")
open(f"{REPO}/2026/2026-q2-baseline.html","w").write(add_tips(q2_page()))
print("wrote 2026-q2-baseline")


# ---------------------------------------------------------------- releases
# Second pass. A release is the same kind of period as a month, so it renders
# through the same engine; what changes is the window, the span (a release runs
# two sprints, sometimes three) and what it compares itself against — its own
# series rather than the calendar quarters, which belong to the quarter pages.
RELEASES = DATA.get("RELEASES", {})
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
    _b = band([cl(k) for k in MK_L3])
    Q2 = dict(thr_med=round(_b["mean"]), thr_avg=_b["mean"], unit="/sprint",
              unp=round(sum(_unp(k) for k in MK_L3)/len(MK_L3), 1),
              cyc_med=round(sum(CYC[k]["med"] for k in MK_L3)/len(MK_L3), 2),
              cyc_avg=round(sum(CYC[k]["avg"] for k in MK_L3)/len(MK_L3), 2),
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
        if _r.get("open"):
            _a = dt.date.fromisoformat(_r["start"]); _b = dt.date.fromisoformat(_r["end"])
            _r["days"] = (_b - _a).days + 1
            _r["day"]  = max(1, min(_r["days"], (dt.date.today() - _a).days + 1))

    REPORTS = [[v["short"], v["slug"] + ".html"] for k, v in sorted(RELEASES.items())]
    REPORTS += [r for r in DATA["REPORTS"] if r[0].startswith("Q")]

    for rk, r in RELEASES.items():
        open(f"{REPO}/2026/{r['slug']}.html", "w").write(add_tips(month_page(rk)))
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

open(os.path.join(REPO, "index.html"), "w").write(index_page())
print("wrote index")

_froze = freeze_month()
_q = quarter_ready()
if _q:
    print(f"NOTE: {_q} now has all of its months frozen and no quarter page yet.")
