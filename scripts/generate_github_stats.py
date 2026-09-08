#!/usr/bin/env python3
"""Fetch live GitHub stats and write Tokyo Night SVG cards.

Stars, commits, PRs, issues, followers, languages, total contributions, and
longest streak refresh every 6 hours. Current streak follows GitHub's own
contribution-day rules and timezone, so it only changes when GitHub's
calendar would change it — not on the 6-hour clock.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

USERNAME = "jubayir-hub-69"
API = "https://api.github.com/graphql"
OUT = Path(__file__).resolve().parent.parent / "stats"


def github_today() -> date:
    """GitHub contribution 'today' in the profile timezone (Dhaka, UTC+6)."""
    try:
        return datetime.now(ZoneInfo("Asia/Dhaka")).date()
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=6)).date()

THEME = {
    "title": "#70a5fd",
    "icon": "#bf91f3",
    "text": "#38bdae",
    "bg": "#1a1b27",
    "muted": "#565f89",
    "ring": "#bb9af7",
}


def token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GH_PAT"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("No GitHub token found. Set GITHUB_TOKEN or run gh auth login.") from exc


def graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token()}",
            "Content-Type": "application/json",
            "User-Agent": "jubayir-hub-69-stats",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        hint = f"HTTP {exc.code}"
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("message"):
                hint = f"HTTP {exc.code}: {parsed['message']}"
        except json.JSONDecodeError:
            pass
        raise SystemExit(f"GitHub GraphQL request failed ({hint})") from None
    errors = payload.get("errors") or []
    if errors:
        messages = []
        for err in errors:
            if isinstance(err, dict) and err.get("message"):
                messages.append(str(err["message"]))
        raise SystemExit("GitHub GraphQL errors: " + "; ".join(messages or ["unknown error"]))
    return payload["data"]


USER_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    name
    login
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(
      first: 1
      contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
    ) { totalCount }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

REPOS_MORE = """
query ($login: String!, $cursor: String!) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

YEAR_COMMITS = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch() -> dict:
    now = datetime.now(timezone.utc)
    data = graphql(
        USER_QUERY,
        {
            "login": USERNAME,
            "from": iso(now - timedelta(days=365)),
            "to": iso(now + timedelta(days=1)),
        },
    )["user"]

    repos = list(data["repositories"]["nodes"])
    page = data["repositories"]["pageInfo"]
    while page["hasNextPage"]:
        extra = graphql(REPOS_MORE, {"login": USERNAME, "cursor": page["endCursor"]})
        block = extra["user"]["repositories"]
        repos.extend(block["nodes"])
        page = block["pageInfo"]

    created = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
    commits = 0
    for year in range(created.year, now.year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        year_data = graphql(
            YEAR_COMMITS,
            {"login": USERNAME, "from": iso(start), "to": iso(end)},
        )["user"]["contributionsCollection"]
        commits += year_data["totalCommitContributions"] + year_data["restrictedContributionsCount"]

    stars = sum(repo["stargazerCount"] for repo in repos)
    langs: dict[str, dict] = {}
    totals: dict[str, int] = defaultdict(int)
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] += edge["size"]
            langs[name] = {"name": name, "color": edge["node"]["color"] or "#8b949e", "size": totals[name]}

    ranked = sorted(langs.values(), key=lambda item: item["size"], reverse=True)
    days = []
    for week in data["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            days.append((date.fromisoformat(day["date"]), int(day["contributionCount"])))
    days.sort()

    return {
        "name": data["name"] or data["login"],
        "stars": stars,
        "commits": commits,
        "prs": data["pullRequests"]["totalCount"],
        "issues": data["issues"]["totalCount"],
        "contributed_to": data["repositoriesContributedTo"]["totalCount"],
        "followers": data["followers"]["totalCount"],
        "languages": ranked,
        "days": days,
        "year_contributions": data["contributionsCollection"]["contributionCalendar"]["totalContributions"],
    }


def _count_back(counts: dict[date, int], start: date) -> tuple[int, date, date]:
    length = 0
    cursor = start
    start_day = start
    while counts.get(cursor, 0) > 0:
        length += 1
        start_day = cursor
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return length, start_day, start


def streak_stats(days: list[tuple[date, int]]) -> dict:
    if not days:
        return {
            "current": 0,
            "longest": 0,
            "current_start": None,
            "current_end": None,
            "longest_start": None,
            "longest_end": None,
            "total": 0,
        }

    counts = {day: count for day, count in days}
    total = sum(counts.values())

    longest = 0
    longest_start = longest_end = None
    run = 0
    run_start = None
    cursor = days[0][0]
    last = days[-1][0]
    while cursor <= last:
        if counts.get(cursor, 0) > 0:
            if run == 0:
                run_start = cursor
            run += 1
            if run > longest:
                longest = run
                longest_start, longest_end = run_start, cursor
        else:
            run = 0
            run_start = None
        cursor = date.fromordinal(cursor.toordinal() + 1)

    # Current streak uses GitHub's contribution-day clock, not the 6-hour job.
    # Days are in the profile timezone. An empty *today* does not break the
    # streak until that calendar day is over — same as github.com.
    today = github_today()
    yesterday = today - timedelta(days=1)
    if counts.get(today, 0) > 0:
        current, current_start, current_end = _count_back(counts, today)
    elif counts.get(yesterday, 0) > 0:
        current, current_start, current_end = _count_back(counts, yesterday)
    else:
        current, current_start, current_end = 0, None, None

    return {
        "current": current,
        "longest": longest,
        "current_start": current_start,
        "current_end": current_end,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "total": total,
    }


def fmt(n: int) -> str:
    return f"{n:,}"


def fmt_date(d: date | None) -> str:
    if d is None:
        return "—"
    return d.strftime("%b %d, %Y")


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


ICONS = {
    "star": "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25",
    "commits": "M1.643 3.143L.427 1.927A.25.25 0 000 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 0 00.177-.427L2.715 4.215a6.5 6.5 0 11-1.18 4.458.75.75 0 10-1.493.154 8.001 8.001 0 101.6-5.684zM7.75 4a.75.75 0 01.75.75v2.992l2.028.812a.75.75 0 01-.557 1.392l-2.5-1A.75.75 0 017 8.25v-3.5A.75.75 0 017.75 4z",
    "prs": "M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z",
    "issues": "M8 9.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3z M8 0a8 8 0 100 16A8 8 0 008 0zM1.5 8a6.5 6.5 0 1113 0 6.5 6.5 0 01-13 0z",
    "contrib": "M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8zM5 12.25v3.25a.25.25 0 00.4.2l1.45-1.087a.25.25 0 01.3 0L8.6 15.7a.25.25 0 00.4-.2v-3.25a.25.25 0 00-.25-.25h-3.5a.25.25 0 00-.25.25z",
    "followers": "M10.561 8.073a6.005 6.005 0 013.432 5.142.75.75 0 11-1.499.044 4.5 4.5 0 00-8.988 0 .75.75 0 01-1.5-.044 6.004 6.004 0 013.431-5.142 3.999 3.999 0 115.124 0zM5.5 4a2.5 2.5 0 115 0 2.5 2.5 0 01-5 0z",
}


def icon(name: str, x: int, y: int) -> str:
    return (
        f'<svg x="{x}" y="{y}" width="16" height="16" viewBox="0 0 16 16" fill="{THEME["icon"]}">'
        f'<path d="{ICONS[name]}"/></svg>'
    )


def stats_svg(stats: dict) -> str:
    rows = [
        ("star", "Total Stars", stats["stars"]),
        ("commits", "Total Commits", stats["commits"]),
        ("prs", "Total PRs", stats["prs"]),
        ("issues", "Total Issues", stats["issues"]),
        ("contrib", "Contributed to", stats["contributed_to"]),
        ("followers", "Followers", stats["followers"]),
    ]
    height = 50 + len(rows) * 28 + 18
    items = []
    for i, (key, label, value) in enumerate(rows):
        y = 58 + i * 28
        items.append(
            f'{icon(key, 24, y - 12)}'
            f'<text class="stat" x="48" y="{y}">{escape(label)}:</text>'
            f'<text class="stat" x="220" y="{y}">{fmt(value)}</text>'
        )
    return f"""<svg width="495" height="{height}" viewBox="0 0 495 {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escape(stats['name'])}'s GitHub Stats">
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['title']}; }}
    .stat {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['text']}; }}
  </style>
  <rect width="495" height="{height}" rx="8" fill="{THEME['bg']}"/>
  <text class="header" x="24" y="36">{escape(stats['name'])}'s GitHub Stats</text>
  {"".join(items)}
</svg>
"""


def langs_svg(langs: list[dict]) -> str:
    top = langs[:6]
    total = sum(item["size"] for item in top) or 1
    height = 44 + 12 + len(top) * 22 + 16
    width = 340
    bar_y = 48
    segments = []
    x = 24
    bar_w = width - 48
    legend = []
    for i, item in enumerate(top):
        pct = item["size"] / total
        w = max(2, round(bar_w * pct))
        color = item["color"]
        segments.append(f'<rect x="{x}" y="{bar_y}" width="{w}" height="8" fill="{color}"/>')
        x += w
        ly = 74 + i * 22
        legend.append(
            f'<circle cx="32" cy="{ly - 4}" r="4" fill="{color}"/>'
            f'<text class="lang" x="44" y="{ly}">{escape(item["name"])}</text>'
            f'<text class="pct" x="{width - 24}" y="{ly}" text-anchor="end">{pct * 100:.1f}%</text>'
        )
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top Languages">
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['title']}; }}
    .lang {{ font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['text']}; }}
    .pct {{ font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['muted']}; }}
  </style>
  <rect width="{width}" height="{height}" rx="8" fill="{THEME['bg']}"/>
  <text class="header" x="24" y="32">Most Used Languages</text>
  {"".join(segments)}
  {"".join(legend)}
</svg>
"""


def streak_svg(streak: dict) -> str:
    current_range = (
        f"{fmt_date(streak['current_start'])} — {fmt_date(streak['current_end'])}"
        if streak["current"]
        else "No active streak"
    )
    longest_range = (
        f"{fmt_date(streak['longest_start'])} — {fmt_date(streak['longest_end'])}"
        if streak["longest"]
        else "—"
    )
    return f"""<svg width="660" height="195" viewBox="0 0 660 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Streak">
  <style>
    .label {{ font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['title']}; }}
    .num {{ font: 800 28px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['text']}; }}
    .sub {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['muted']}; }}
    .big {{ font: 800 36px 'Segoe UI', Ubuntu, Sans-Serif; fill: {THEME['ring']}; }}
  </style>
  <rect width="660" height="195" rx="8" fill="{THEME['bg']}"/>
  <g transform="translate(110,98)" text-anchor="middle">
    <text class="num" y="0">{fmt(streak['total'])}</text>
    <text class="label" y="28">Total Contributions</text>
    <text class="sub" y="48">Past year</text>
  </g>
  <g transform="translate(330,98)" text-anchor="middle">
    <circle cx="0" cy="-8" r="46" fill="none" stroke="{THEME['ring']}" stroke-width="3"/>
    <text class="big" y="6">{fmt(streak['current'])}</text>
    <text class="label" y="58">Current Streak</text>
    <text class="sub" y="76">{escape(current_range)}</text>
  </g>
  <g transform="translate(550,98)" text-anchor="middle">
    <text class="num" y="0">{fmt(streak['longest'])}</text>
    <text class="label" y="28">Longest Streak</text>
    <text class="sub" y="48">{escape(longest_range)}</text>
  </g>
</svg>
"""


def write(path: Path, content: str) -> None:
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def main() -> int:
    stats = fetch()
    streak = streak_stats(stats["days"])
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "github-stats.svg", stats_svg(stats))
    write(OUT / "top-langs.svg", langs_svg(stats["languages"]))
    write(OUT / "streak.svg", streak_svg(streak))
    print(
        "stars={stars} commits={commits} prs={prs} issues={issues} "
        "contributed_to={contributed_to} followers={followers} "
        "current_streak={current} longest_streak={longest} year_contrib={year} "
        "github_today={today}".format(
            current=streak["current"],
            longest=streak["longest"],
            year=streak["total"],
            today=github_today().isoformat(),
            **stats,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
