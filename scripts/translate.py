#!/usr/bin/env python3
"""Builds a Spanish copy of the report for review.

This is a translation, not a second edition. The pages keep their structure, their
numbers and their claims; only the words change. Nothing here reinterprets, softens
or improves a sentence -- if the English overstates something, the Spanish overstates
the same thing, and the fix belongs in the English.

How it works: the site is built normally, then every text node is looked up in
assets/i18n/es.json by its shape, with the digits replaced by {n}. One entry covers
every period, because "17 of 51 closed items (33%)" and "8 of 40 closed items (20%)"
are the same sentence. The numbers are put back in the order they came out, and a
translation whose placeholder count does not match its source is a build error rather
than a quietly moved figure.

Deliberately NOT translated:
  * Jira status names (In Development, Ready for Development, Won't Do...). They are
    what the board literally says; translating them would make the report describe a
    board nobody can find.
  * Sprint and release names, field names, metric names used as proper nouns
    (Throughput, Cycle Time, Story Points, Definition of Ready).
  * Anything written by a person in Confluence -- sprint goals, practice changes,
    roster notes. Those arrive already written and this tool has no business
    rewriting them. They stay in whatever language they were typed in.

Output goes to _es/, which GitHub Pages does not serve: this is a review copy.
"""
import json, os, re, sys, shutil, argparse
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_TAGS = {"script", "style", "title"}
NUM = re.compile(r"\d+(?:[.,]\d+)?")

# Text that is a name, not a sentence. Left exactly as it is.
KEEP = {
    "In Development", "Ready for Development", "Awaiting Review", "Backlog", "To Do",
    "Closed", "Won't Do", "Deferred", "Done", "Resolved", "Idea", "Draft", "Groomed",
    "Story", "Bug", "Task", "Spike", "Sub-task", "Epic", "Urgent Task", "Unplanned",
    "Throughput", "Cycle Time", "Story Points", "Definition of Ready", "WIP",
    "Jira", "Confluence", "EDW", "DS", "Wellfit", "ScrumBan", "Scrum",
}


def shape(s):
    """The sentence with its digits removed, which is the dictionary key."""
    return NUM.sub("{n}", s)


def restore(template, numbers):
    """Put the digits back, in the order they were taken out."""
    out, i = [], 0
    for part in re.split(r"(\{n\})", template):
        if part == "{n}":
            out.append(numbers[i] if i < len(numbers) else "{n}")
            i += 1
        else:
            out.append(part)
    return "".join(out)


class Translator(HTMLParser):
    def __init__(self, table, stats):
        super().__init__(convert_charrefs=False)
        self.table, self.stats = table, stats
        self.stack, self.out = [], []

    # everything that is not a text node is copied through untouched
    def handle_decl(self, d): self.out.append(f"<!{d}>")
    def handle_comment(self, d): self.out.append(f"<!--{d}-->")
    def handle_pi(self, d): self.out.append(f"<?{d}>")
    def handle_entityref(self, n): self.out.append(f"&{n};")
    def handle_charref(self, n): self.out.append(f"&#{n};")

    def _tag(self, tag, attrs, close=False):
        a = "".join(
            f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs)
        return f"<{tag}{a}{'/' if close else ''}>"

    # HTMLParser lower-cases tag and attribute names. SVG is case-sensitive --
    # viewBox and preserveAspectRatio stop working if they come back lowercased --
    # so tags are copied through byte for byte as they were written, and only the
    # text between them is ever touched.
    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        self.out.append(self.get_starttag_text() or self._tag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.out.append(self.get_starttag_text() or self._tag(tag, attrs, close=True))

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if any(t in SKIP_TAGS for t in self.stack) or not data.strip():
            self.out.append(data); return
        lead = data[:len(data) - len(data.lstrip())]
        tail = data[len(data.rstrip()):]
        body = data.strip()
        if body in KEEP or len(body) < 2:
            self.out.append(data); return
        key = shape(body)
        es = self.table.get(key)
        self.stats["seen"].add(key)
        if es is None:
            self.stats["missing"].add(key)
            self.out.append(data); return
        nums = NUM.findall(body)
        if es.count("{n}") != key.count("{n}"):
            raise SystemExit(
                f"translation drops or invents a number:\n  en: {key}\n  es: {es}")
        self.stats["hit"].add(key)
        self.out.append(lead + restore(es, nums) + tail)

    def result(self):
        return "".join(self.out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_es")
    ap.add_argument("--report", action="store_true",
                    help="print every phrase still missing a translation")
    a = ap.parse_args()

    table = json.load(open(os.path.join(ROOT, "assets", "i18n", "es.json"),
                           encoding="utf-8"))
    table = {k: v for k, v in table.items() if not k.startswith("_")}
    stats = {"seen": set(), "hit": set(), "missing": set()}

    dest = os.path.join(ROOT, a.out)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.join(dest, "2026"), exist_ok=True)

    pages = [f for f in os.listdir(ROOT) if f.endswith(".html")]
    pages += [os.path.join("2026", f) for f in os.listdir(os.path.join(ROOT, "2026"))
              if f.endswith(".html")]
    for rel in pages:
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        t = Translator(table, stats)
        t.feed(src)
        html = t.result().replace('<html lang="en"', '<html lang="es"', 1)
        open(os.path.join(dest, rel), "w", encoding="utf-8").write(html)

    # the data the pages read at runtime travels with them
    for d in ("data", "assets"):
        s = os.path.join(ROOT, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, d), dirs_exist_ok=True)
    if os.path.exists(os.path.join(ROOT, "live.js")):
        shutil.copy(os.path.join(ROOT, "live.js"), dest)

    n_seen, n_hit = len(stats["seen"]), len(stats["hit"])
    pct = 100 * n_hit / n_seen if n_seen else 0
    print(f"{a.out}/: {len(pages)} pages, {n_hit} of {n_seen} phrases translated "
          f"({pct:.0f}%)")
    if stats["missing"]:
        print(f"still in English: {len(stats['missing'])} phrases")
        if a.report:
            # JSON on one line each: a phrase can contain newlines, so printing it
            # raw made the list unusable as input to anything, including a person
            # copying it into the dictionary.
            for k in sorted(stats["missing"], key=lambda s: (-len(s.split()), s)):
                print("   ", json.dumps(k, ensure_ascii=False))


if __name__ == "__main__":
    main()
