#!/usr/bin/env python3
"""Refresh the 'By the numbers' block in README.md from the GitHub GraphQL API.

Needs env GH_STATS_TOKEN: a classic personal access token with ONLY the
read:user and read:org scopes (no repo access). Private contributions are
included when 'Private contributions' is enabled on the profile.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

LOGIN = os.environ.get("PROFILE_LOGIN", "senkop")
README = os.environ.get("README_PATH", "README.md")
START, END = "<!--STATS:START-->", "<!--STATS:END-->"


def gql(query, variables, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-stats-updater"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch(token, today):
    head = gql(
        "query($l:String!){user(login:$l){createdAt organizations(first:50){nodes{login url}}}}",
        {"l": LOGIN}, token)["user"]
    first_year = int(head["createdAt"][:4])
    parts = []
    for y in range(first_year, today.year + 1):
        to = f"{y}-12-31T23:59:59Z" if y < today.year else f"{today.isoformat()}T23:59:59Z"
        parts.append(
            f'y{y}: contributionsCollection(from:"{y}-01-01T00:00:00Z", to:"{to}")'
            "{contributionCalendar{weeks{contributionDays{date contributionCount}}}}")
    data = gql("query($l:String!){user(login:$l){" + " ".join(parts) + "}}",
               {"l": LOGIN}, token)["user"]
    days = {}
    for cal in data.values():
        for w in cal["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    return days, head["organizations"]["nodes"]


def load(today):
    mock = os.environ.get("STATS_MOCK")
    if mock:  # local testing only
        m = json.load(open(mock))
        return m["days"], m["orgs"]
    token = os.environ.get("GH_STATS_TOKEN")
    if not token:
        raise SystemExit("GH_STATS_TOKEN is not set")
    return fetch(token, today)


def compute(days, today):
    active = sorted(dt.date.fromisoformat(d) for d, c in days.items() if c > 0)
    best, run, best_range, start, prev = 0, 0, None, None, None
    for d in active:
        if prev and (d - prev).days == 1:
            run += 1
        else:
            run, start = 1, d
        if run > best:
            best, best_range = run, (start, d)
        prev = d
    have = set(active)
    cur, d = 0, today if today in have else today - dt.timedelta(days=1)
    while d in have:
        cur, d = cur + 1, d - dt.timedelta(days=1)
    per_year = {}
    for k, c in days.items():
        per_year[int(k[:4])] = per_year.get(int(k[:4]), 0) + c
    return {"total": sum(days.values()), "active": len(active), "longest": best,
            "range": best_range, "current": cur, "per_year": per_year}


def fmt_range(a, b):
    if a.year == b.year:
        return f"{a:%b} {a.day} – {b:%b} {b.day}, {b.year}"
    return f"{a:%b} {a.day}, {a.year} – {b:%b} {b.day}, {b.year}"


def render(s, orgs, today):
    org_links = " and ".join(f'<a href="{o["url"]}">{o["login"]}</a>' for o in orgs) or "none yet"
    years = sorted(y for y, c in s["per_year"].items() if c > 0)[-3:]
    cells = "\n".join(
        f'    <td align="center" width="215"><b>{y}</b><br/>{s["per_year"][y]:,}'
        f'{" so far" if y == today.year else ""}</td>' for y in years)
    rng = fmt_range(*s["range"]) if s["range"] else "-"
    return f"""<table align="center">
  <tr>
    <td align="center" width="215"><h2>{s['total']:,}</h2><b>Contributions</b><br/><sub>across all orgs and private repos</sub></td>
    <td align="center" width="215"><h2>{s['active']:,}</h2><b>Active days</b><br/><sub>days with at least one contribution</sub></td>
    <td align="center" width="215"><h2>{s['longest']} days</h2><b>Longest streak</b><br/><sub>{rng}</sub></td>
    <td align="center" width="215"><h2>{s['current']} day{'s' if s['current'] != 1 else ''}</h2><b>Current streak</b><br/><sub>{len(orgs)} organization{'s' if len(orgs) != 1 else ''}: {org_links}</sub></td>
  </tr>
</table>

<table align="center">
  <tr>
{cells}
  </tr>
</table>

<p align="center"><sub>Contributions per year, private work included. Updated automatically on {today:%b} {today.day}, {today.year}.</sub></p>"""


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    days, orgs = load(today)
    block = f"{START}\n{render(compute(days, today), orgs, today)}\n{END}"
    text = open(README, encoding="utf-8").read()
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pat.search(text):
        raise SystemExit("Stats markers not found in README.md")
    open(README, "w", encoding="utf-8").write(pat.sub(lambda _: block, text, count=1))
    print("README updated")


if __name__ == "__main__":
    sys.exit(main())
