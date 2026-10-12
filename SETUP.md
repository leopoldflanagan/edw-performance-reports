# Live data — setup

The site stays static. A scheduled job rewrites one small file, `data/live.json`,
and the index page reads it in the browser. Closed months and quarters never change.

## 1. Create a Jira API token

id.atlassian.com → Security → **Create API token**. Copy it once; you cannot see it again.

## 2. Add it to the repository

Settings → Secrets and variables → Actions.

**Secrets** (encrypted, never visible again):

| Name | Value |
|---|---|
| `JIRA_BASE` | `https://wellfit.atlassian.net` |
| `JIRA_EMAIL` | the Atlassian account the token belongs to |
| `JIRA_TOKEN` | the token from step 1 |

**The board and project** live in the workflow's `env:` block, and the same three
values are in `config/team.json`. Both are checked against each other before the
run starts, so they cannot drift apart:

| Name | EDW | DS | Plans |
|---|---|---|---|
| `TEAM_KEY` | `EDW` | `DS` | `PLANS` |
| `BOARD_ID` | `11` | `257` | `15` |
| `PROJECT_KEY` | `EDW` | `DS` | `PLANS` |

(This table used to say the DS project key was `Database Services`. It is `DS` —
that is the project key; `Database Services` is the team's name. Nothing read the
table, so nothing broke, which is why it stayed wrong.)

**Everything else about a team** — what counts as a delivered item, which statuses
are terminal, how reactive work is marked, which Confluence pages are this team's,
and which pods share the board — is in `config/team.json`. A value that team does
not have is left out, and the report says so rather than borrowing another team's.

## 3. Add the files

- `scripts/fetch_jira.py`
- `.github/workflows/refresh.yml`
- `live.js`
- `data/live.json` (a placeholder; the job overwrites it)

## 4. Run it once by hand

Actions → **Refresh live data** → *Run workflow*. It should finish green and commit
`data/live.json`. If it fails, the log names the reason — a 401 means the token or the
email is wrong, a 403 usually means the token has no access to that board.

## 5. Trigger it every 5 minutes from cron-job.org

GitHub's own `schedule:` is best effort and gets throttled, so it is only the fallback
here. For a tight interval, have cron-job.org call the dispatch endpoint:

- **URL** `https://api.github.com/repos/leopoldflanagan/edw-performance-reports/dispatches`
- **Method** `POST`
- **Headers**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <GitHub token>`
  - `Content-Type: application/json`
- **Body** `{"event_type":"refresh"}`

The GitHub token is a **fine-grained personal access token**, scoped to this one
repository, with a single permission: **Contents: read and write**. Nothing else.
Set it to expire and renew it — a token that lives in a third-party scheduler forever
is the part of this setup most worth keeping short.

A successful dispatch returns **204 No Content** with an empty body. cron-job.org will
show it as a success.

## What refreshes and what does not

| | Refreshes | Frozen |
|---|---|---|
| Active sprint panel (index) | ✅ every run | |
| Month in progress (index) | ✅ every run | |
| Monthly reports (May–Aug) | | ✅ as published |
| Quarter reports (Q1, Q2) | | ✅ as published |

That split is deliberate. The numbers in a closed month are final, and the written
analysis around them was based on those numbers — regenerating them would let the two
drift apart silently.

## Cost control

The workflow skips the commit when only the timestamp moved, so an idle board does not
produce a commit every five minutes. Actions minutes are free on public repositories;
on a private one this uses roughly 1 minute per run.
