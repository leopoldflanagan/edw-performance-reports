/* Live panel — reads data/live.json, written by the scheduled Action.
   Everything else on the site stays static. If the file is missing or stale,
   the panel says so instead of showing nothing. */
(function () {
  var host = document.getElementById('livepanel');
  if (!host) return;

  var STCOL = {
    'Ready for Development': '#65B2D5', 'In Development': '#007CBC',
    'Awaiting Review': '#ED7D31', 'Backlog': '#c3cdda', 'To Do': '#c3cdda',
    'Closed': '#4FA800', "Won't Do": '#9aa6b8'
  };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };
  var ago = function (iso) {
    var m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (!isFinite(m)) return '';
    if (m < 2) return 'just now';
    if (m < 60) return m + ' min ago';
    var h = Math.round(m / 60);
    return h < 24 ? h + 'h ago' : Math.round(h / 24) + 'd ago';
  };

  function tile(k, v, n, col) {
    return '<div class="hcell"><div class="hk">' + k + '</div>' +
      '<div class="hv"' + (col ? ' style="color:' + col + '"' : '') + '>' + v + '</div>' +
      '<div class="hn">' + n + '</div></div>';
  }

  function bar(dist) {
    var tot = 0, k;
    for (k in dist) tot += dist[k];
    if (!tot) return '';
    var pairs = Object.keys(dist).map(function (s) { return [s, dist[s]]; })
      .sort(function (a, b) { return b[1] - a[1]; });
    var bars = '', keys = '';
    pairs.forEach(function (p) {
      var pct = 100 * p[1] / tot, col = STCOL[p[0]] || '#c3cdda';
      bars += '<span style="width:' + pct.toFixed(1) + '%;background:' + col + '">' +
        (pct > 7 ? p[1] : '') + '</span>';
      keys += '<span><i class="tisdot" style="background:' + col + '"></i>' +
        esc(p[0]) + ' <b>' + p[1] + '</b></span>';
    });
    return '<div class="sprintsec"><div class="sk">Work distribution &middot; ' + tot +
      ' items</div><div class="tisbar">' + bars + '</div>' +
      '<div class="tiskey">' + keys + '</div></div>';
  }

  function sparkline(burn, scope) {
    if (!burn || burn.length < 2) return '';
    var w = 620, h = 150, pad = 8;
    var hi = Math.max.apply(null, scope.concat(burn)) || 1;
    var step = (w - 2 * pad) / (burn.length - 1);
    var pt = function (arr, i) {
      return [pad + i * step, pad + (h - 2 * pad) * (1 - arr[i] / hi)];
    };
    var path = function (arr) {
      return arr.map(function (_, i) {
        var p = pt(arr, i); return (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1);
      }).join(' ');
    };
    var area = path(scope) + ' L' + (pad + (scope.length - 1) * step).toFixed(1) + ',' +
      (h - pad) + ' L' + pad + ',' + (h - pad) + ' Z';
    var ideal = 'M' + pad + ',' + pt(scope, 0)[1].toFixed(1) +
      ' L' + (pad + (burn.length - 1) * step).toFixed(1) + ',' + (h - pad);
    return '<div class="sprintsec"><div class="sk">Burndown &middot; ' + burn.length +
      ' days so far</div><svg viewBox="0 0 ' + w + ' ' + h +
      '" style="width:100%;height:150px" role="img" aria-label="Sprint burndown">' +
      '<path d="' + area + '" fill="rgba(195,205,218,.28)"/>' +
      '<path d="' + ideal + '" stroke="#ED7D31" stroke-dasharray="5 4" stroke-width="2" fill="none"/>' +
      '<path d="' + path(scope) + '" stroke="#c3cdda" stroke-width="2" fill="none"/>' +
      '<path d="' + path(burn) + '" stroke="#007CBC" stroke-width="3" fill="none" stroke-linejoin="round"/>' +
      '</svg></div>';
  }

  function render(d) {
    var s = d.sprint, m = d.month, out = '';
    var first = !d.generated || d.generated.slice(0,4) === '1970';
    var stale = !first && (Date.now() - new Date(d.generated).getTime()) > 45 * 60000;

    var tag = d.kind === 'active'
      ? '<span class="activetag">&#9679; Active sprint</span>'
      : (d.kind === 'recent'
        ? '<span class="activetag" style="background:var(--wf-muted)">Most recent sprint</span>'
        : '<span class="activetag" style="background:var(--wf-muted)">No sprint open</span>');

    out += '<div class="activewrap">' + tag;

    if (d.kind !== 'active') {
      out += '<div class="secsub" style="margin-bottom:10px">No sprint is open on this board right now' +
        (s ? ' — <b>' + esc(s.name) + '</b> closed on ' + esc(s.end) + '.' : '.') +
        (d.next ? ' <b>' + esc(d.next.name) + '</b> is created with a start date of ' +
          esc(d.next.start) + ' and has not been started.' : '') + '</div>';
    } else if (d.next) {
      out += '<div class="secsub" style="margin-bottom:10px">Next up: <b>' + esc(d.next.name) +
        '</b>, starting ' + esc(d.next.start) + '.</div>';
    }

    if (s) {
      out += '<div class="healthrow">' +
        tile('Work complete', (s.vs_commitment == null ? '—' : s.vs_commitment + '%'),
          s.completed + ' of ' + s.committed + ' pts committed') +
        tile('Time elapsed', s.time_elapsed + '%', esc(s.start) + ' → ' + esc(s.end)) +
        tile('Scope change', (s.scope_change == null ? '—' : '+' + s.scope_change + '%'),
          s.committed + ' → ' + s.final + ' pts', 'var(--warning)') +
        tile('Spillover', (s.spill_rate == null ? '—' : s.spill_rate + '%'),
          (s.spill.open_pts + s.spill.out_pts) + ' pts not finished', 'var(--risk)') +
        '</div>';
      out += bar(s.dist);
      out += sparkline(s.burn, s.scope);
      out += '<div class="goalbox" style="margin-top:12px">' + (s.goal
        ? '<b>Sprint goal.</b> ' + esc(s.goal)
        : '<b>No goal recorded in Jira for this sprint.</b> Without one there is nothing to measure delivery against beyond the point count.') +
        '</div>';
    }

    if (m) {
      out += '<div class="sprintsec"><div class="sk">' + esc(m.label) +
        ' so far &middot; day ' + m.day + '</div><div class="healthrow" style="margin-bottom:0">' +
        tile('Closed', m.closed, 'items this month') +
        tile('Story points', m.points, 'delivered so far') +
        tile('Unplanned', (m.unplanned_pct == null ? '—' : m.unplanned_pct + '%'),
          m.unplanned + ' of ' + m.closed + ' items') +
        tile('Team', m.people_active, 'people with closed work') +
        '</div></div>';
    }

    out += '<div class="secsub" style="margin-top:12px">' + (first
      ? 'Waiting for the first refresh — the scheduled job has not run yet.'
      : 'Live from Jira · updated ' + ago(d.generated) +
        (stale ? ' · <b style="color:var(--warning)">the refresh job may be stuck</b>' : '')) +
      '</div></div>';
    host.innerHTML = out;
  }

  fetch('data/live.json?t=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(function () {
      host.innerHTML = '<div class="activewrap"><span class="activetag" ' +
        'style="background:var(--wf-muted)">Live panel</span>' +
        '<div class="goalbox">Live data is not available yet. Once the refresh job has run ' +
        'at least once, the current sprint and the month in progress appear here.</div></div>';
    });
})();
