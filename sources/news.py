"""
Live news feed ingestion.

Pulls RSS from the major football outlets, parses with the stdlib (no
feedparser dependency), then for each article:
  - tags which national teams are mentioned (so news attaches to fixtures),
  - flags the *kind* of news (injury / suspension / lineup / form / transfer)
    via keyword detection — these are the signals that should nudge a model.

Stored in the `news` table, deduped on link. This is the "inflow" layer: run
it on a schedule and the freshest team news is always queryable next to the
predictions.
"""
from __future__ import annotations
import re
import datetime as dt
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

import config
from db import connect

_UA = {"User-Agent": "WorldCup2026-Predictor/1.0 (research; contact sambowey1110@gmail.com)"}

# Keyword -> flag. Lower-cased substring match on title+summary.
_FLAG_KEYWORDS = {
    "injury": ["injury", "injured", "ruled out", "doubt", "fitness", "strain",
               "knock", "hamstring", "acl", "sidelined", "out for"],
    "suspension": ["suspended", "suspension", "ban", "banned", "red card",
                   "sent off", "dismissed"],
    "lineup": ["line-up", "lineup", "starting xi", "team news", "squad", "named",
               "call-up", "called up", "recall"],
    "form": ["win", "won", "beat", "defeat", "loss", "draw", "thrash", "comeback",
             "streak", "unbeaten"],
    "transfer": ["transfer", "signs", "signing", "move to", "deal", "joins"],
    "manager": ["manager", "head coach", "sacked", "appointed", "boss"],
}


def _team_index() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM teams WHERE is_active ORDER BY length(name) DESC"
        ).fetchall()
    return [r[0] for r in rows]


def _detect_teams(text: str, teams: list[str]) -> list[str]:
    low = text.lower()
    found = []
    for t in teams:
        # word-ish boundary so "Iran" doesn't fire inside "Iranian" oddly etc.
        if re.search(r"\b" + re.escape(t.lower()) + r"\b", low):
            found.append(t)
    return found


def _detect_flags(text: str) -> list[str]:
    low = text.lower()
    return [flag for flag, kws in _FLAG_KEYWORDS.items()
            if any(kw in low for kw in kws)]


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def fetch_feed(name: str, url: str, teams: list[str]) -> list[tuple]:
    resp = requests.get(url, headers=_UA, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        summary = _strip_html(item.findtext("description") or "")
        pub = _parse_date(item.findtext("pubDate"))
        blob = f"{title} {summary}"
        tagged = _detect_teams(blob, teams)
        flags = _detect_flags(blob)
        if not link:
            continue
        items.append((pub, name, title, link, summary[:1000], tagged, flags))
    return items


def ingest(verbose: bool = True) -> dict:
    teams = _team_index()
    total, kept = 0, 0
    with connect() as conn:
        for name, url in config.NEWS_FEEDS:
            try:
                items = fetch_feed(name, url, teams)
            except Exception as exc:  # one bad feed shouldn't sink the run
                if verbose:
                    print(f"  {name}: skipped ({exc})")
                continue
            total += len(items)
            for pub, src, title, link, summary, tagged, flags in items:
                cur = conn.execute(
                    """
                    INSERT INTO news (published, source, title, link, summary, teams, flags)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (link) DO NOTHING
                    """,
                    (pub, src, title, link, summary, tagged, flags),
                )
                kept += cur.rowcount
            if verbose:
                print(f"  {name}: {len(items)} items")
    if verbose:
        print(f"  ingested {kept} new of {total} fetched")
    return {"fetched": total, "new": kept}


def recent(limit: int = 20, team: str | None = None) -> list[tuple]:
    with connect() as conn:
        if team:
            return conn.execute(
                """SELECT published, source, title, flags FROM news
                   WHERE %s = ANY(teams) ORDER BY published DESC NULLS LAST LIMIT %s""",
                (team, limit),
            ).fetchall()
        return conn.execute(
            """SELECT published, source, title, flags, teams FROM news
               ORDER BY published DESC NULLS LAST LIMIT %s""",
            (limit,),
        ).fetchall()


if __name__ == "__main__":
    print(ingest())
    print("\n  Latest flagged items:")
    for row in recent(12):
        pub, src, title, flags, teams = row
        when = pub.strftime("%m-%d %H:%M") if pub else "  ?  "
        tag = f" {teams}" if teams else ""
        fl = f" [{','.join(flags)}]" if flags else ""
        print(f"   {when} {src[:10]:<10} {title[:60]}{fl}{tag}")
