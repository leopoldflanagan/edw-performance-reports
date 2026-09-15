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
    _mk = CURRENT["ym"].split("-")[1]
    # Frozen wins only for a sprint that belongs to a month already closed. A sprint
    # recorded while it was still open is provisional: the fresh reading replaces it.
    _final = {n for ns in SP_BY_MONTH.values() for n in ns} | {r[0] for r in SPRINTS_Q1}
    _fresh = {r[0] for r in CURRENT["SPRINTS"]} - _final
    SPRINTS[:] = [r for r in SPRINTS if r[0] not in _fresh]
    SPRINTS.extend([r for r in CURRENT["SPRINTS"] if r[0] not in _final])
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
MK_LABS = [MONTH_ABBR[int(k)-1] for k in MK_DONE]

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
    n=len(keys)
    it=sum(CAP[k][0] for k in keys); sp=sum(CAP[k][1] for k in keys)
    pt=sum(CAP[k][2] for k in keys); pe=sum(CAP[k][3] for k in keys)/n
    return dict(items=it/n, pts=pt/n, size=pt/sp, people=pe, per=(pt/n)/pe)

def band(vals):
    """Expected range from the series' own month-to-month movement (XmR)."""
    mr=[abs(vals[i]-vals[i-1]) for i in range(1,len(vals))]
    mrbar=sum(mr)/len(mr); mean=sum(vals)/len(vals); half=2.66*mrbar
    return dict(lo=max(0,mean-half), hi=mean+half, mean=mean, move=mrbar,
                consistency=100*mrbar/mean)

def trend(keys_now, keys_prev):
    a=sum(CAP[k][0] for k in keys_now)/len(keys_now)
    b=sum(CAP[k][0] for k in keys_prev)/len(keys_prev)
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

def sb_rows(rows):
    """Uniform delta block: label | value | vs Q1 | vs Q2. rows = [(label, value_str, d1, d2, better_low)]"""
    out = ['<div class="statblock"><div class="sb sb-head"><span></span><span>This month</span><span>vs Q1</span><span>vs Q2</span></div>']
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
    r = _review(slug)
    if r.get("status") == "reviewed":
        who = r.get("by", "")
        when = r.get("date", "")
        tail = " · ".join([x for x in (who, when) if x])
        return f'<span class="revchip ok"><span class="ic">&#10003;</span> Reviewed{(" · " + tail) if tail else ""}</span>'
    return ('<span class="revchip pend"><span class="ic">&#9679;</span> '
            'Generated from Jira · pending review</span>')


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

def sprint_card(name, idx, note=""):
    n,st,en,items,done,comm,final,comp,chg,burn,scope = sp(name)
    pct = round(100*comp/comm) if comm else 0
    open_sp = final - comp
    sl = spill(n) or dict(done=(0,0), open=(0,0), out=(0,0))
    gone_i = sl["open"][0] + sl["out"][0]
    gone_p = sl["open"][1] + sl["out"][1]
    if gone_p:
        bits = []
        if sl["out"][0]:  bits.append(f"{sl['out'][0]} removed before the sprint closed")
        if sl["open"][0]: bits.append(f"{sl['open'][0]} still open at close")
        sr = spill_rate(n)
        spill_html = (f'<div class="spill"><div class="sk">Spillover</div>'
                      f'<div class="sv">{sr["rate"]:.0f}%<span style="font-size:14px;color:var(--wf-muted);font-weight:600"> &middot; {gone_p} of {sr["allp"]} pts</span></div>'
                      f'<div class="sn">{gone_i} items — {" · ".join(bits)}. '
                      f'The burndown reaches zero because this work left the sprint, not because it was finished.</div></div>')
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
     <div class="sh"><div class="k">vs commitment</div><div class="v">{pct}%</div><div class="n">completed against day-1 scope</div></div>
   </div>
   <div class="chartbox" style="height:310px"><canvas id="bd{idx}"></canvas></div>
   {spill_html}
   {goal_box(n)}
   {tis_block(n)}
   {stalled_block(n)}
   {note}
 </div>"""

def month_scrum_insight(mk):
    names = SP_BY_MONTH[mk]
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
 <div class="insightbox" style="margin-bottom:24px"><div class="k">This month\'s sprints</div>
  <h2>Scope grew {span} after the sprints had started, and {gone_p} points left the sprints without finishing.</h2>
  <p>{tail} The series-wide view — velocity, scope-change trend and the full sprint table — lives in the
  <a href="#" class="ip-link" data-goto="cmp" style="color:#fff;border-bottom:1px solid rgba(255,255,255,.5)">Comparatives tab</a>.</p>
 </div>'''

def sprint_table(names, short=False):
    rows = ""
    for n in names:
        _,st,en,items,done,c0,final,comp_sp,chg,_,_ = sp(n)
        pct = round(100*comp_sp/c0) if c0 else 0
        tag = ' <span style="color:var(--wf-muted)">in progress</span>' if n == ACTIVE else ""
        sl = SPLIT.get(n, SPLIT_Q1.get(n))
        cells = (f'<td>{sl["react"]}</td><td class="neg">{sl["plan"]}</td><td>{sl["pct"]}%</td>' if sl
                 else '<td class="flat">no data</td><td class="flat">no data</td><td class="flat">—</td>')
        sl2 = spill(n) or dict(open=(0,0), out=(0,0))
        gp = sl2["open"][1] + sl2["out"][1]
        gcell = (f'<td class="neg">{gp}</td>' if gp else '<td>0</td>')
        rows += (f'<tr><td>{n}{tag}</td><td>{st} - {en}</td><td>{c0}</td><td>+{final-c0}</td>'
                 f'<td>{comp_sp}</td>{gcell}<td>{pct}%</td>{cells}</tr>')
    return f'''<div class="tscroll"><table class="exec">
  <thead><tr><th>Sprint</th><th>Dates</th><th>Committed</th><th>Added</th><th>Completed</th><th>Left sprint</th><th>vs commit</th><th>Added: reactive</th><th>Added: plannable</th><th>% reactive</th></tr></thead>
  <tbody>{rows}</tbody>
 </table></div>'''

def scrum_tab(mk=None, names=None, title="Sprint metrics", sub="Every sprint of the series, rebuilt from Jira.", intro=""):
    """Monthly page: only this month's sprints. Quarter page: the whole series."""
    if mk and mk in SP_BY_MONTH:
        names = SP_BY_MONTH[mk]
        cards = "".join(sprint_card(n, i) for i, n in enumerate(names))
        extra = ""
        if mk == MK_LAST and ACTIVE and ACTIVE not in names and sp(ACTIVE):
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
        return f"""
<section class="panel" id="scrum">
 <div class="sectit">Sprint metrics — {MONTH_LABEL[mk]}</div>
 <div class="secsub">The sprints that closed this month, rebuilt from Jira.</div>
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
    b  = band([CAP[k][0] for k in MK_L3])
    b0 = band([CAP[k][0] for k in ["01","02","03","04","05"]])
    ss = spill_series([r[0] for r in SPRINTS])
    tr = trend(MK_L3, MK_P3)
    now  = sum(CAP[k][0] for k in MK_L3)/len(MK_L3)
    prev = sum(CAP[k][0] for k in MK_P3)/len(MK_P3)
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
  <div class="infopanel ip-amber">There is no sprint goal recorded on any of these sprints, so spillover cannot be read against what the sprint set out to achieve — only against the points. Recording a goal is what would make the difference between "we dropped 48 points" and "we dropped 48 points and still got there".</div>
 </div>
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
    if not only:
        b = band([CAP[k][0] for k in MK_L3])
        labs = MK_LABS
        vals = [CAP[k][0] for k in MK_DONE]
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

    pairs = [(n, i) for i, n in enumerate(lst)]
    if mk == MK_LAST and ACTIVE and ACTIVE not in lst and sp(ACTIVE):
        pairs.append((ACTIVE, 90))
    for n, i in pairs:
        row = sp(n); burn, scope = row[9], row[10]
        labels = json.dumps([f"d{d}" for d in range(len(burn))])
        ideal = json.dumps([round(scope[0]*(1-d/(len(burn)-1)),1) for d in range(len(burn))])
        js += f"""
new Chart(document.getElementById('bd{i}'),{{type:'line',
 data:{{labels:{labels},datasets:[
  {{label:'Total scope',data:{json.dumps(scope)},borderColor:GREY,backgroundColor:'rgba(195,205,218,.25)',fill:true,tension:.2,pointRadius:0,borderWidth:2}},
  {{label:'Work still open',data:{json.dumps(burn)},borderColor:BLUE,backgroundColor:'rgba(0,124,188,.10)',fill:true,tension:.2,pointRadius:3,borderWidth:3}},
  {{label:'Ideal from day-1 commitment',data:{ideal},borderColor:AMBER,borderDash:[5,4],pointRadius:0,borderWidth:2,fill:false}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gridc}},title:{{display:true,text:'Story points'}}}},x:{{grid:{{display:false}},title:{{display:true,text:'Sprint day'}}}}}}}}}});"""
    return js

def month_page(mk):
    m = MONTHS[mk]
    cm  = cap([mk]); cq1 = cap(CAP_Q1); cq2 = cap(CAP_Q2)
    bnd = band([CAP[k][0] for k in MK_L3])
    in_band = bnd["lo"] <= CAP[mk][0] <= bnd["hi"]
    st_thr = "healthy" if in_band else "warning"
    # A month in progress is compared at pace, never as a total: 29 items on day 15
    # is not "29 against 82", it is a run rate. The baselines are cut to the same
    # share of the month so the two sides of the comparison cover the same ground.
    OPEN = bool(m.get("open"))
    SHARE = (m.get("day", 30) / m.get("days", 30)) if OPEN else 1.0
    PACE = m["closed"] / SHARE if SHARE else m["closed"]
    pace_note = ('' if not OPEN else
        f'<div class="ctxline"><span>At this pace the month lands near <b>{PACE:.0f} items</b>. '
        f'Every comparison below is cut to the same {100*SHARE:.0f}% of a month on both sides.</span></div>')
    dev_base = (m["closed"] - Q1["thr_med"]*SHARE) / (Q1["thr_med"]*SHARE) * 100
    dev_q2   = (m["closed"] - Q2["thr_med"]*SHARE) / (Q2["thr_med"]*SHARE) * 100
    dev_prev = (m["closed"] - m["prev_closed"]*SHARE) / (m["prev_closed"]*SHARE) * 100
    types = " · ".join(f"{n} {t}" for t,n in m["types"])

    # unplanned card
    if m["unplanned"] is None:
        unp_card = f"""<div class="card">
      <div class="ghead"><span class="gname">Planned vs Unplanned</span><span class="badge" style="background:#eef1f6;color:#69727d"><span class="d" style="background:#8b95a8"></span>No data</span></div>
      <div class="nodata" style="margin:10px 0"><span class="big">—</span>0 items labeled <i>Unplanned</i> {"so far this month" if m.get("open") else "in the whole month"}</div>
      <div class="targetline"><span class="tl">Target</span> &le;5% · Warning 5-10% · Risk &gt;10%</div>
      <div class="infopanel ip-amber">Zero labels in a month of {m['closed']} deliveries does not mean zero reactive work: it means the labeling stopped being applied. Publishing 0% would invent an improvement the team did not have. The labeling follow-up has been open since the May retro.</div>
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
      {sb_rows([("Unplanned share", f"{m['unp_pct']:.1f}%", 100*(m['unp_pct']-Q1['unp'])/Q1['unp'], 100*(m['unp_pct']-Q2['unp'])/Q2['unp'], True),
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
     <div class="nodata"><span class="big">0 labels</span>across {m['closed']} deliveries {"so far this month" if m.get("open") else "this month"}</div>
     <div class="fnote">{m.get("note_unp") or f"Zero labels across {m['closed']} deliveries describes the labeling, not the work. Without this label the predictability metric stops existing, and it is the only one that explains why a month with good throughput can still be unstable."}</div>
   </div>"""

    disc_note = ""
    if m["discarded"] >= 5:
        pct_d = 100*m["discarded"]/m["resolved"]
        disc_note = f"""<div class="act"><div class="pri p-grey"></div><div class="inner">
     <div class="atop"><h4>Review the {m['discarded']} discarded items</h4><span class="pill pill-grey">Follow-up</span></div>
     <p>The official Throughput filter uses <i>resolved</i>, which mixes closed with discarded (Won't Do). This month that is {m['discarded']} of {m['resolved']} resolved ({pct_d:.0f}%), which is why the headline counts only the {m['closed']} closed. Worth looking at in the retro at what was opened and then dropped — it usually signals work that came in without enough definition.</p>
     <div class="owner">Follow-up by: <b>EDW</b></div></div></div>"""

    ip_thr = {"healthy":"ip-green","warning":"ip-amber","risk":"ip-red"}[st_thr]
    col_thr = {"healthy":"num-green","warning":"num-amber","risk":"num-red"}[st_thr]
    c = CYC[mk]
    cyc_st = cyc_status(c)
    col_cyc = {"healthy":"num-green","warning":"num-amber","risk":"num-red"}[cyc_st]
    nodev_pct = 100*c["nodev"]/c["base"]

    html = head(f"{m['label']} Performance Report",
                f"Flow and sprint metrics for the month, against {m['prev']} 2026 and the closed quarters of the year: Q1 and Q2 2026.",
                f"Flow Health: {BADGE[m['status']][1].upper()} — {m['headline']}", m["status"], m["short"])

    html += f"""
<section class="panel active" id="dash">
  <div class="sectit">Flow metrics — {m['label']}</div>
  <div class="secsub">Throughput counts closed items only; discarded work is reported separately.</div>
  <div class="grid g3">
    <div class="card">
      <div class="ghead"><span class="gname">Throughput</span>{badge(st_thr)}</div>
      <div class="bignum {col_thr}">{m['closed']}<span class="unit">{"closed · day " + str(m.get("day")) + " of " + str(m.get("days")) if OPEN else "closed · month"}</span></div>
{pace_note}
      <div class="secondary">{types}</div>
      {sb_rows([("Items closed", f"{cm['items']:.0f}", 100*(cm['items']/(cq1['items']*SHARE)-1), 100*(cm['items']/(cq2['items']*SHARE)-1), False),
                ("Story points", f"{cm['pts']:.0f}", 100*(cm['pts']/(cq1['pts']*SHARE)-1), 100*(cm['pts']/(cq2['pts']*SHARE)-1), False)])}
      <div class="ctxline"><span>Average item size <b>{cm['size']:.2f} pts</b> <i>(Q1 {cq1['size']:.2f})</i></span>
        <span>Team <b>{cm['people']:.0f} active</b> <i>(Q1 {cq1['people']:.1f})</i></span></div>
      <div class="spark-cap">Items closed · {MK_LABS[0]} to {MK_LABS[-1]}{" · this month is still running and is not plotted" if mk not in MK_DONE else ""}</div>
      {spark([CAP[k][0] for k in MK_DONE], _sidx(mk))}
      <div class="infopanel {ip_thr}">On top of the {m['closed']} closed there were <b>{m['discarded']} discarded</b> (Won't Do), which are not deliveries.
        Items are {"" if OPEN else "up "}{100*(cm['items']/(cq1['items']*SHARE)-1):+.0f}% on Q1 while points are {"" if OPEN else "up "}{100*(cm['pts']/(cq1['pts']*SHARE)-1):+.0f}%{" at the same point in the month" if OPEN else " — the team is larger and the items are smaller"}.
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
      <div class="ctxline"><span>Measured on <b>{c['n']} of {c['base']}</b> closed items <i>({100*c['n']/c['base']:.0f}% of the month)</i></span></div>
      <div class="spark-cap">Median cycle time · May to Aug</div>
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
    <thead><tr><th>Metric</th><th>{m['label'].split()[0]}</th><th>{m['prev']}</th><th>Q1 2026</th><th>Q2 2026</th><th>vs Q1</th><th>vs Q2</th></tr></thead>
    <tbody>
      <tr><td>Throughput (closed)</td><td>{m['closed']}</td><td>{m['prev_closed']}</td><td>{Q1['thr_med']}</td><td>{Q2['thr_med']}</td><td class="{'pos' if dev_base>0 else 'neg'}">{dev_base:+.1f}%</td><td class="{'pos' if dev_q2>0 else 'neg'}">{dev_q2:+.1f}%</td></tr>
      <tr><td>Unplanned work</td>{unp_row}</tr>
      <tr><td>Cycle Time (median)</td><td>{c['med']:.2f}d</td><td class="flat">—</td><td>{Q1['cyc_med']}d</td><td>{Q2['cyc_med']}d</td><td class="{'neg' if c['med']>Q1['cyc_med'] else 'pos'}">{100*(c['med']-Q1['cyc_med'])/Q1['cyc_med']:+.1f}%</td><td class="{'neg' if c['med']>Q2['cyc_med'] else 'pos'}">{100*(c['med']-Q2['cyc_med'])/Q2['cyc_med']:+.1f}%</td></tr>
      <tr><td>Closed without entering development</td><td>{c['nodev']} ({nodev_pct:.0f}%)</td><td class="flat">—</td><td class="flat">—</td><td>{Q2['nodev']}</td><td class="flat">—</td><td class="flat">—</td></tr>
    </tbody>
  </table></div>
  <div class="fnote">Comparatives use the closed quarters of the year: Q1 and Q2. Q3 joins this table once September closes and its report is created. Q1's monthly detail is under review — the figure used here is the one published in Confluence.</div>
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
  <div class="cmpcard">
    <div class="cmphead"><h3><span class="st-dot" style="background:{BADGE[st_thr][2]};width:13px;height:13px"></span> Throughput</h3>{badge(st_thr)}</div>
    <div class="cmpgrid">
      <div class="chartbox" style="height:250px"><canvas id="cThru"></canvas></div>
      <div class="readout">
        <div class="line" style="border-color:{BADGE[st_thr][2]}"><span class="vs-tag">vs Q1 ({Q1['thr_med']}/mo)</span><br><b>{dev_base:+.1f}%</b> in items — but {100*(cm['per']/cq1['per']-1):+.0f}% once item size and team size are taken out. Most of the gap is a bigger team closing smaller items.</div>
        <div class="line" style="border-color:{BADGE[st_thr][2]}"><span class="vs-tag">vs Q2 ({Q2['thr_med']}/mo)</span><br><b>{dev_q2:+.1f}%</b> — and Q2 is a poor yardstick anyway: its median is set by April and May, under the previous team.</div>
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
   <p>Of the {c['base']} items closed this month, {c['nodev']} ({nodev_pct:.0f}%) never recorded a transition into <i>In Development</i>: they went from backlog or the previous column straight to closed. Those tickets have no Cycle Time, so the metric is computed over the remaining {c['n']}. In May it was {CYC['may']['nodev']} of 39 ({100*CYC['may']['nodev']/39:.0f}%). It may be genuinely trivial work, or tickets closed without going through the flow — worth telling apart, because it changes how much Cycle Time really represents the month's work.</p>
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
 data:{{labels:['Apr','May','Jun','Jul','Aug'],datasets:[{{label:'Closed',
  data:[{APR},{MAY},74,79,82],backgroundColor:['#c3cdda','#c3cdda','{'#007CBC' if mk=='06' else '#65B2D5'}','{'#007CBC' if mk=='07' else '#65B2D5'}','{'#007CBC' if mk=='08' else '#65B2D5'}'],borderRadius:6}}]}},
 options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,max:110,grid:{{color:gridc}},title:{{display:true,text:'Items closed'}}}},x:{{grid:{{display:false}}}}}}}},
 plugins:[thrRef]}});
new Chart(document.getElementById('cCyc'),{{type:'bar',
 data:{{labels:['Q1','Q2','May','Jun','Jul','Aug'],datasets:[
  {{label:'Median',data:[{Q1['cyc_med']},{Q2['cyc_med']},{CYC['may']['med']},{CYC['06']['med']},{CYC['07']['med']},{CYC['08']['med']}],backgroundColor:BLUE,borderRadius:5}},
  {{label:'Average',data:[{Q1['cyc_avg']},{Q2['cyc_avg']},{CYC['may']['avg']},{CYC['06']['avg']},{CYC['07']['avg']},{CYC['08']['avg']}],backgroundColor:BLUEL,borderRadius:5}}]}},
 options:{{plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,max:11,grid:{{color:gridc}},title:{{display:true,text:'Days'}}}},x:{{grid:{{display:false}}}}}}}}}});
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
{charts_scrum(mk)}"""
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + TIPJS)

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
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + TIPJS)

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
    return html + FOOT.replace("__CHARTS__", charts).replace("{ZOOMJS}", ZOOMJS + TIPJS)


# ---------------------------------------------------------------- index page
BADGE_LABEL = {"healthy": "Healthy", "warning": "Warning", "risk": "Risk"}
BADGE_BG    = {"healthy": ("#e6f6ef", "#1a7f5a"), "warning": ("#fdeee3", "#c0641f"),
               "risk": ("#fdeaea", "#b3261e")}

def _card(href, short, year, title, badge, blurb, status=None):
    bg, fg = BADGE_BG.get(status, ("#fdeee3", "#c0641f"))
    r = _review(href)
    pend = ('<span class="badge" style="background:#eef2f8;color:#5a6577">Pending review</span>'
            if r.get("status") != "reviewed" else "")
    return f'''<a class="rcard" href="2026/{href}">
<div class="mo"><span class="m">{short}</span><span class="y">{year}</span></div>
<div class="body"><h3>{title} <span class="badge" style="background:{bg};color:{fg}">{badge}</span>{pend}</h3>
<p>{blurb}</p></div>
<div class="arrow">&rarr;</div></a>
'''

def index_page():
    head = open(os.path.join(REPO, "assets", "index.head.html")).read()
    foot = open(os.path.join(REPO, "assets", "index.foot.html")).read()
    idx  = DATA.get("INDEX", {})

    months, quarters = [], []
    for short, href in REPORTS:
        meta = dict(idx.get(href, {}))
        if not meta:                       # a month the job created on its own
            mk = next((k for k, v in MONTHS.items() if v["slug"] + ".html" == href), None)
            m  = MONTHS.get(mk, {})
            meta = {"short": m.get("short", short), "title": f"{m.get('label', short)} Performance Report",
                    "badge": BADGE_LABEL.get(m.get("status"), "Warning"),
                    "blurb": m.get("headline", "")}
        mk = next((k for k, v in MONTHS.items() if v["slug"] + ".html" == href), None)
        status = MONTHS.get(mk, {}).get("status") if mk else None
        # the card badge must say what the page's own header says
        badge = BADGE_LABEL.get(status, meta["badge"]) if status else meta["badge"]
        card = _card(href, meta["short"], "2026", meta["title"], badge, meta["blurb"], status)
        (quarters if short.startswith("Q") else months).append((href, card))

    months.sort(key=lambda t: t[0], reverse=True)      # newest first
    quarters.sort(key=lambda t: t[0], reverse=True)

    return (head
            + '\n<div class="yeartag">2026 · Monthly Reports</div>\n'
            + "".join(c for _, c in months)
            + '<div class="yeartag" style="margin-top:30px">2026 · Quarter Reports</div>\n'
            + "".join(c for _, c in quarters)
            + foot)


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
for mk, m in MONTHS.items():
    open(f"{REPO}/2026/{m['slug']}.html","w").write(add_tips(month_page(mk)))
    print("wrote", m["slug"])
open(f"{REPO}/2026/2026-q1.html","w").write(add_tips(q1_page()))
print("wrote 2026-q1")
open(f"{REPO}/2026/2026-q2-baseline.html","w").write(add_tips(q2_page()))
print("wrote 2026-q2-baseline")

open(os.path.join(REPO, "index.html"), "w").write(index_page())
print("wrote index")

_froze = freeze_month()
_q = quarter_ready()
if _q:
    print(f"NOTE: {_q} now has all of its months frozen and no quarter page yet.")
