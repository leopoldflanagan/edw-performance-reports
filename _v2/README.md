# Version 2 — four ideas, prototyped

`prototype.html` is a single self-contained page. Open it in a browser; it needs no
server and no network. It is **not part of the site**: this folder starts with an
underscore, and GitHub Pages runs Jekyll here, which does not serve those. Nothing
in it writes to Jira or Confluence.

It was built on 2026-09-16 against the board's real numbers so the four ideas could
be judged rather than described. The data is frozen inside the file — it will not
refresh, and it is not meant to.

The plan is deliberately slow: version 1 ships, the team gets used to reading it,
and these land one at a time.

---

## 1 · Forecast the backlog, not the sprint

**What it does.** Monte Carlo over the team's own closures per sprint, against the
backlog in Jira rank order, mapped onto the sprint calendar from the capacity page
(holidays included). Answers "when do I get the thing I asked for" with a range and
a confidence instead of a date pulled out of a meeting.

**What it found, which was not the plan.** The forecast does not hold on this board.
37 of the 40 backlog items have already waited more than three times longer than the
model says the entire queue ahead of them still needs. Median age in the list is nine
months; the oldest is 2.4 years. Rank is not what decides what gets worked on here.

So the page audits its own assumption and says so, rather than printing dates. That
audit turned out to be worth more than the forecast, and it is the piece to build
first: it needs only the backlog order and each item's `created` date.

**Data needed in production.** Backlog in rank order (`ORDER BY Rank ASC`), `created`
per item, closures per sprint (already collected), the forward sprint calendar
(already on the capacity page).

**Open question.** The drain rate — what share of a sprint's closures come off the
ordered backlog — is measured at 27% from lead times, but it is a proxy. A real
measurement needs backlog snapshots over time, which nothing records today.

## 2 · The clock the person who asked is watching

**What it does.** Adds lead time (created → closed) beside cycle time (In Development
→ closed). Same items, two start lines.

**What it found.** Team clock 5.0d median. Request clock 6.9d median, 19.7d average,
56d at the 85th percentile. The typical item waits about two extra days; the average
hides ten. Five of 37 sampled items took longer than four sprints from the day
somebody filed them.

**Data needed in production.** `created` on closed items — one extra field on a query
the collector already runs. This is the cheapest of the four.

**Worth doing next.** It will make the reports look worse, which is the point: the
number the team's customers experience is not currently on any chart.

## 3 · Findings as rules, not prose

**What it does.** Each finding becomes a named rule evaluated over the release series.
It appears when it becomes true, carries the release it first appeared in, and
disappears when the team fixes it. The prototype ships six rules; four fire, two have
cleared.

**Why it matters more than it looks.** The Findings & Retro tab is prose written for
one period. When the next release closes it still describes the last one and nothing
tells anybody. This is the same failure as a hand-written sprint goal or a
hand-written label — a human description standing in for generated content — and it
lives in the largest tab of the report.

**Data needed in production.** None. Every rule in the prototype runs on data the
reports already compute.

**Design note.** The "cleared" list is half the value. A rule that stopped being true
is the only evidence a team ever gets that something they changed worked.

## 4 · Did the thing we changed work?

**What it does.** Reads the Practice changes table, and two periods after a change
reports the before and after of the metric it was meant to move.

**What it needs from the team.** Two columns on that table: **Metric** (one of the
numbers the reports already compute) and **Expected direction** (up, down, steady).
Without the second one a change cannot fail, which means it cannot teach anybody
anything.

**What the prototype shows.** The spillover change from sprint 22-26 correctly
refuses to answer — it needs two closed sprints and has none. The roster change
(seven people to four, from sprint 19-26) reads 37.7 → 32.0 items per sprint, −15%,
in the direction the team expected.

**Cheapest of the four to build, and the one most likely to change a retro.**

---

## Order to build them

1. **The queue audit** from idea 1, and **lead time** from idea 2. Both are small,
   both are uncomfortable, both say something the reports cannot say today.
2. **Idea 4**, once the two columns exist on the capacity page.
3. **Idea 3**, as a refactor of the Findings tab rather than an addition.
4. The **forecast itself**, only once the board behaves enough like a queue for dates
   to mean anything. Until then it is arithmetic about a fiction, and the page says so.

## What not to do

Do not put EDW and DS side by side in a ranking table. The reports spend half a page
explaining why team size and work mix make that comparison lie. Compare the method,
not the numbers.
