import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio

TOOLS = {
    "tv_channels",
    "tv_channel_schedule",
    "tv_live_now",
    "tv_search",
    "tv_program",
    "tv_episode",
    "tv_live_events",
}
GW = "/kandoo"


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name


async def test_channels_filter(client, api):
    api[f"{GW}/channel/getChannelsList/"] = fixture("channels.json")
    r = (await client.call_tool("tv_channels", {})).structured_content
    assert r["count"] == 4 and r["channels"][0] == {
        "id": "tv1",
        "name": "شبکه 1",
        "kind": "national",
        "archive": True,
        "url": "https://telewebion.ir/live/tv1",
    }
    r = (await client.call_tool("tv_channels", {"kind": "radio"})).structured_content
    assert [c["id"] for c in r["channels"]] == ["radioava"]


async def test_schedule_sorted_with_urls(client, api):
    api[f"{GW}/channel/getChannelEpisodesByDate/"] = fixture("schedule.json")
    r = (await client.call_tool("tv_channel_schedule", {"channel": "tv3", "date": "2026-11-16"})).structured_content
    starts = [e["started"] for e in r["episodes"]]
    assert starts == sorted(starts) and starts[-1] == "2026-11-16 12:58"
    assert r["episodes"][-1]["url"] == "https://telewebion.ir/episode/0x16d2f97f"
    q = api.calls[0].url.params
    assert q["FromDate"] == "2026-11-16T00:00:00" and q["IsClip"] == "false"


async def test_schedule_bad_date_and_channel(client, api):
    r = await client.call_tool("tv_channel_schedule", {"channel": "tv3", "date": "16/11"})
    assert r.is_error
    api[f"{GW}/channel/getChannelEpisodesByDate/"] = {"body": {"queryChannel": []}}
    r = await client.call_tool("tv_channel_schedule", {"channel": "nope", "date": "2026-11-16"})
    assert r.is_error and "tv_channels" in r.content[0].text


async def test_live_now_scans_channels(client, api):
    api[f"{GW}/channel/getChannelsList/"] = fixture("channels.json")
    api[f"{GW}/channel/getChannelEpisodesByDate/"] = fixture("schedule.json")
    r = (await client.call_tool("tv_live_now", {})).structured_content
    assert len(r["channels"]) == 3 and r["channels"][0]["live_url"] == "https://telewebion.ir/live/tv1"
    assert r["channels"][0]["latest"]["program"]


async def test_search_programs_and_movies(client, api):
    api["/pouya2/api/v8/search"] = fixture("search.json")
    r = (await client.call_tool("tv_search", {"query": "فوتبال"})).structured_content
    assert r["programs"][0]["url"].startswith("https://telewebion.ir/program/0x")
    assert r["movies_series"][0]["url"].startswith("https://telewebion.ir/product/0x")
    assert api.calls[0].url.params["q"] == "فوتبال"


async def test_program_episodes(client, api):
    api[f"{GW}/program/getEpisodesByProgramID/"] = fixture("program.json")
    r = (await client.call_tool("tv_program", {"program_id": "0x11e5eaeb"})).structured_content
    assert r["title"] == "پایتخت 7" and len(r["episodes"]) == 3
    assert r["episodes"][0]["url"] == "https://telewebion.ir/episode/0x12de42a9"


async def test_episode_has_no_tokens(client, api):
    api[f"{GW}/episode/getEpisodeDetail/"] = fixture("episode.json")
    r = (await client.call_tool("tv_episode", {"episode_id": "0x12de42a9"})).structured_content
    assert r["channel_id"] == "tv1" and r["minutes"] == 46 and r["qualities"] == ["480p", "720p", "1080p"]
    assert "token" not in str(r).lower() and "eyJ" not in str(r)
    assert r["program_url"] == "https://telewebion.ir/program/0x11e5eaeb"


async def test_live_events_filters_to_day(client, api):
    api[f"{GW}/v1/component/live-event-conductor/"] = fixture("live_events.json")
    r = (await client.call_tool("tv_live_events", {"date": "2026-11-16"})).structured_content
    assert r["events"] and all(e["start"].startswith("2026-11-16") for e in r["events"])
    assert r["events"][0]["url"].startswith("https://telewebion.ir/live-event/")

    # feed is UTC; site shows +3:30 (13:00Z -> 16:30), and an end before the start is dropped
    assert r["events"][0]["start"] == "2026-11-16 16:30" and not r["events"][0].get("end")
