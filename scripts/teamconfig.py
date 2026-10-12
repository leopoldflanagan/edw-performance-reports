"""The vocabulary one team uses, read from config/team.json instead of written
into the code.

Every defect this system has produced so far was a hand-typed value that was true
for one team and false for another: the page footer, the index promise, the chart
colour, the sign-off link, the release calendar, the Confluence page ids. Not one
was a logic error. The measurement method is universal; the words each team uses
for it are not. This file is where those words live now.

Two rules the rest of the code depends on:

  need()  is for a value the run cannot proceed without. It stops the run, by
          name, before anything touches Jira -- two seconds here instead of a
          six-minute round trip that ends in another team's numbers.

  opt()   is for a value a team may legitimately not have: a label it does not
          apply, a Confluence page it has not written. It returns Absent, which
          is false, carries the reason, and is rendered as a dash with that
          reason beside it. It is never silently replaced by a default, because
          a default here is another team's truth.
"""

import json
import os
import sys


class Absent:
    """A value this team has not configured, and the reason, carried together.

    Falsy on purpose, so `if cfg.opt(...)` reads naturally, and self-describing
    so a renderer can print why the figure is missing rather than printing 0.
    """

    __slots__ = ("key", "why")

    def __init__(self, key, why):
        self.key, self.why = key, why

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())           # safe to splat into a set() or a loop

    def __len__(self):
        return 0

    def __repr__(self):
        return f"<not configured: {self.key} -- {self.why}>"

    __str__ = __repr__


class TeamConfig:
    def __init__(self, data, path):
        self._d, self.path = data, path

    # -------------------------------------------------------------- lookup
    def _walk(self, dotted):
        cur = self._d
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None, False
            cur = cur[part]
        return cur, True

    def need(self, dotted):
        """A value without which the run would report something untrue."""
        val, found = self._walk(dotted)
        if not found or val is None or val == "" or val == []:
            sys.exit(
                f"CONFIG ERROR: {self.path} has no value for '{dotted}'.\n"
                f"  This run would otherwise measure something, publish it, and be\n"
                f"  wrong without failing. Add it to the file and run again.")
        return val

    def opt(self, dotted, why):
        """A value a team may legitimately not have. Returns the value or Absent."""
        val, found = self._walk(dotted)
        if not found or val is None or val == "" or val == []:
            return Absent(dotted, why)
        return val

    def set_(self, dotted):
        """A configured list as a set. An unconfigured one is an empty set, which
        is the honest reading of 'this team names no status that way'."""
        val, found = self._walk(dotted)
        return set(val) if found and val else set()

    # --------------------------------------------------------------- pods
    def pods(self):
        """The delivery pods inside one team.

        Most teams have exactly one, and then this is a formality that changes
        nothing. Plans has two -- Plans and LL -- sharing a board and a project,
        with sprints that do not line up, which is why this is a list and not a
        prefix. A pod is identified by how its sprints are named, because that is
        the only thing in Jira that actually separates them.
        """
        raw = self._d.get("pods") or []
        if not raw:
            return [{"key": self.need("team"), "name": self.need("label"),
                     "sprint_prefix": None}]
        return raw

    def pod_of(self, sprint_name):
        """Which pod a sprint belongs to, or None when it belongs to none of them.

        None is a real answer, not an error: other teams' sprints sit on the same
        board, and work closed outside any sprint belongs to no pod at all. Both
        are reported as themselves rather than folded into whichever pod is first.
        """
        if not sprint_name:
            return None
        for p in self.pods():
            pre = p.get("sprint_prefix")
            if pre and sprint_name.startswith(pre):
                return p["key"]
        return None


REQUIRED = ["team", "label", "project", "board",
            "counts.exclude_types", "counts.done_statuses",
            "flow.terminal_statuses"]


def load(repo):
    path = os.path.join(repo, "config", "team.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"CONFIG ERROR: {path} does not exist.\n"
                 f"  Every team's vocabulary lives in this file now. Copy one from\n"
                 f"  another team's repository and change the values.")
    except json.JSONDecodeError as e:
        sys.exit(f"CONFIG ERROR: {path} is not valid JSON -- {e}")
    return TeamConfig(data, path)


def check(repo):
    """Validate the file without touching Jira, so a bad value fails in two
    seconds in CI rather than after a six-minute run."""
    cfg = load(repo)
    for key in REQUIRED:
        cfg.need(key)
    pods = cfg.pods()
    if len(pods) > 1:
        seen = set()
        for p in pods:
            pre = p.get("sprint_prefix")
            if not pre:
                sys.exit(f"CONFIG ERROR: {cfg.path}: pod '{p.get('key')}' has no\n"
                         f"  sprint_prefix. With more than one pod on a board there is\n"
                         f"  nothing else that tells their sprints apart.")
            if pre in seen:
                sys.exit(f"CONFIG ERROR: {cfg.path}: two pods share the sprint prefix\n"
                         f"  '{pre}'. Every sprint would be counted under the first one.")
            seen.add(pre)
    print(f"config ok: {cfg.need('label')} -- project {cfg.need('project')}, "
          f"board {cfg.need('board')}, "
          f"{len(pods)} pod(s): {', '.join(p['key'] for p in pods)}")
    for key, why in (("reactive.labels", "reactive work"),
                     ("pages.capacity", "the capacity panel"),
                     ("pages.signoff", "the sign-off register")):
        v = cfg.opt(key, why)
        if not v:
            print(f"  not configured: {key} -- {why} will be reported as unavailable")
    return cfg


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    check(root)
