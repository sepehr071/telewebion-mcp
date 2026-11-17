"""Telewebion tools: channels, what aired when, programs, episodes, search and live sports events."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import Field

from .http import API, SITE, ApiError, fetch
from .registry import tool

TEHRAN = timezone(timedelta(hours=3, minutes=30))
KINDS = Literal["national", "provincial", "exclusive", "international", "radio"]
SPORT_SPACE_COMPONENT = "0x16c0ce6a"  # the "live" conductor on the sport space (read from the space page)


def _g(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _ep(e):
    """One episode line; started/ended are Tehran time."""
    p = e.get("program") or {}
    return {
        "id": e.get("EpisodeID"),
        "title": e.get("title"),
        "program": p.get("title"),
        "program_id": p.get("ProgramID"),
        "started": (e.get("started_at") or "")[:16].replace("T", " ") or None,
        "ended": (e.get("ended_at") or "")[:16].replace("T", " ") or None,
        "minutes": round(e["duration"] / 60) if e.get("duration") else None,
        "views": e.get("view_count"),
        "url": f"{SITE}/episode/{e['EpisodeID']}",
    }


def _date(date: str | None) -> str:
    if not date:
        return datetime.now(TEHRAN).strftime("%Y-%m-%d")
    try:
        return datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ApiError("date must look like 2026-11-16 (Gregorian, Tehran day).") from None


def _tehran(ts: str | None) -> str | None:
    if not ts:
        return None
    t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TEHRAN)
    return t.strftime("%Y-%m-%d %H:%M")


async def _day(channel: str, day: str, first: int, offset: int = 0) -> list:
    r = await fetch(
        f"{API}/kandoo/channel/getChannelEpisodesByDate/",
        {
            "ChannelDescriptor": channel,
            "FromDate": f"{day}T00:00:00",
            "ToDate": f"{day}T23:59:59",
            "IsClip": "false",
            "First": first,
            "Offset": offset,
        },
    )
    q = _g(r, "body", "queryChannel") or []
    if not q:
        raise ApiError(f"Unknown channel '{channel}'. Call tv_channels for the ids.")
    return q[0].get("episodes") or []


@tool("Telewebion channels")
async def tv_channels(kind: Annotated[KINDS | None, Field(description="Filter by group; omit for all 89")] = None):
    """List Telewebion live channels (TV, provincial, radio) with the id the other tools take.

    Each row has `id` (use as `channel`), Persian name, group and the live page URL. `archive` false means no
    recorded episodes exist for that channel.
    """
    r = await fetch(f"{API}/kandoo/channel/getChannelsList/", {"NumOfItems": 300})
    rows = [
        {
            "id": c["descriptor"],
            "name": c["name"],
            "kind": _g(c, "type", "descriptor"),
            "archive": c.get("has_archive"),
            "url": f"{SITE}/live/{c['descriptor']}",
        }
        for c in _g(r, "body", "queryChannel") or []
        if kind in (None, _g(c, "type", "descriptor"))
    ]
    return {"count": len(rows), "channels": rows}


@tool("Telewebion channel schedule")
async def tv_channel_schedule(
    channel: Annotated[str, Field(description="Channel id from tv_channels, e.g. tv3, varzesh, irinn")],
    date: Annotated[str | None, Field(description="Gregorian YYYY-MM-DD, Tehran day; default today")] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 40,
):
    """What aired on a channel on a day, oldest first, with start/end (Tehran time) and episode page URLs.

    This is the site's recorded program log, not a forward schedule: Telewebion publishes no future TV guide, and
    the log trails the broadcast by up to an hour or two. Short clips are left out. Use tv_episode for details.
    """
    day = _date(date)
    eps = await _day(channel, day, limit)
    return {
        "channel": channel,
        "date": day,
        "live_url": f"{SITE}/live/{channel}",
        "count": len(eps),
        "episodes": [_ep(e) for e in sorted(eps, key=lambda e: e.get("started_at") or "")],
    }


@tool("Telewebion live now")
async def tv_live_now(
    kind: Annotated[KINDS, Field(description="Channel group to scan")] = "national",
    channels: Annotated[list[str] | None, Field(description="Specific channel ids instead of a group")] = None,
):
    """Show the most recent program on each channel of a group (national TV by default), with live page URLs.

    "Most recent" is the newest logged episode of today, which can trail the live broadcast by up to an hour or
    two. Open `live_url` to actually watch.
    """
    if channels is None:
        r = await tv_channels(kind)
        channels = [c["id"] for c in r["channels"] if c["archive"]]
    day = _date(None)

    async def one(ch):
        try:
            eps = await _day(ch, day, 1)
        except ApiError as e:
            return {"channel": ch, "error": str(e)}
        return {"channel": ch, "live_url": f"{SITE}/live/{ch}", "latest": _ep(eps[0]) if eps else None}

    return {"date": day, "channels": list(await asyncio.gather(*(one(c) for c in channels[:40])))}


@tool("Telewebion search")
async def tv_search(
    query: Annotated[str, Field(description="Persian or English title text")],
    limit: Annotated[int, Field(ge=1, le=30)] = 10,
):
    """Search programs (TV shows) and movies/series by title, with their page URLs.

    Programs have a `program_id` for tv_program; movies and series are on-demand `product` pages only.
    """
    r = await fetch(f"{API}/pouya2/api/v8/search", {"q": query})
    b = r.get("body") or {}
    return {
        "programs": [
            {
                "program_id": p["ProgramID"],
                "title": p.get("title"),
                "title_en": p.get("title_en"),
                "views": p.get("view_count"),
                "url": f"{SITE}/program/{p['ProgramID']}",
            }
            for p in (b.get("program") or [])[:limit]
        ],
        "movies_series": [
            {
                "title": v.get("persian_title"),
                "title_en": v.get("english_title"),
                "type": v.get("content_type"),
                "year": v.get("gregorian_release"),
                "age_limit": v.get("age_limit"),
                "url": f"{SITE}/product/{v['ContentID']}",
            }
            for v in (b.get("vod") or [])[:limit]
        ],
    }


@tool("Telewebion program")
async def tv_program(
    program_id: Annotated[str, Field(description="ProgramID from tv_search or an episode, e.g. 0x11e5eaeb")],
    limit: Annotated[int, Field(ge=1, le=50)] = 12,
    offset: Annotated[int, Field(ge=0)] = 0,
):
    """Show a program's summary and its episodes, newest first, with episode page URLs.

    Page with `offset`. Dates are when the episode was published on the site.
    """
    r = await fetch(
        f"{API}/kandoo/program/getEpisodesByProgramID/", {"ProgramID": program_id, "First": limit, "Offset": offset}
    )
    q = _g(r, "body", "queryProgram") or []
    if not q:
        raise ApiError(f"No program '{program_id}'. Find ids with tv_search.")
    p = q[0]
    return {
        "program_id": program_id,
        "title": p.get("title"),
        "title_en": p.get("title_en"),
        "summary": p.get("summary"),
        "views": p.get("view_count"),
        "url": f"{SITE}/program/{program_id}",
        "offset": offset,
        "episodes": [
            {
                "id": e["EpisodeID"],
                "title": e.get("title"),
                "published": (e.get("created_at") or "")[:10] or None,
                "minutes": round(e["duration"] / 60) if e.get("duration") else None,
                "views": e.get("view_count"),
                "clip": e.get("is_clip"),
                "url": f"{SITE}/episode/{e['EpisodeID']}",
            }
            for e in p.get("episodes") or []
        ],
    }


@tool("Telewebion episode")
async def tv_episode(episode_id: Annotated[str, Field(description="EpisodeID, e.g. 0x12de42a9")]):
    """Show one episode: title, program, channel, air time (Tehran), duration, quality variants and page URL.

    Stream and download tokens are not returned; open `url` to watch.
    """
    r = await fetch(f"{API}/kandoo/episode/getEpisodeDetail/", {"EpisodeId": episode_id})
    q = _g(r, "body", "queryEpisode") or []
    if not q:
        raise ApiError(f"No episode '{episode_id}'.")
    e = q[0]
    p = e.get("program") or {}
    return {
        **_ep(e),
        "description": e.get("description"),
        "published": (e.get("created_at") or "")[:10] or None,
        "channel": _g(e, "channel", "name"),
        "channel_id": _g(e, "channel", "descriptor"),
        "clip": e.get("is_clip"),
        "downloadable": e.get("downloadable"),
        "qualities": [f["variant"] for f in e.get("episode_files") or []],
        "tags": [t["name"] for t in p.get("tags") or [] if t.get("name")],
        "program_url": f"{SITE}/program/{p['ProgramID']}" if p.get("ProgramID") else None,
    }


@tool("Telewebion live sports")
async def tv_live_events(date: Annotated[str | None, Field(description="Gregorian YYYY-MM-DD; default today")] = None):
    """List sports broadcasts (football, volleyball, ...) scheduled or live on Telewebion that day, with page URLs.

    Times are Tehran time (converted from the feed's real UTC). `league` is the competition, `stage` the round.
    """
    day = _date(date)
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=TEHRAN)
    utc = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    r = await fetch(
        f"{API}/kandoo/v1/component/live-event-conductor/",
        {"ComponentID": SPORT_SPACE_COMPONENT, "StartDate": utc(d0), "EndDate": utc(d0 + timedelta(days=1))},
    )
    c = _g(r, "body", "liveEventConductorComponentByDate") or {}
    events = []
    for e in c.get("live_events") or []:
        # feed times end in Z and are real UTC (site shows +3:30); a bad end before start is dropped
        t = [_tehran(e.get(k)) for k in ("start_time", "end_time")]
        if not t[0] or not t[0].startswith(day):
            continue
        events.append(
            {
                "title": e.get("label"),
                "league": e.get("event_context"),
                "stage": e.get("event_stage"),
                "start": t[0],
                "end": t[1] if t[1] and t[1] >= t[0] else None,
                "url": e.get("link"),
            }
        )
    return {"date": day, "events": sorted(events, key=lambda e: e["start"])}
