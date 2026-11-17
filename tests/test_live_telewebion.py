import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

PAYTAKHT = "0x11e5eaeb"
EPISODE = "0x12de42a9"


async def test_live_channels(client):
    r = (await client.call_tool("tv_channels", {})).structured_content
    assert r["count"] > 50 and any(c["id"] == "tv3" for c in r["channels"])


async def test_live_schedule(client):
    r = (await client.call_tool("tv_channel_schedule", {"channel": "tv3"})).structured_content
    assert r["live_url"].endswith("/live/tv3") and "episodes" in r


async def test_live_now(client):
    r = (await client.call_tool("tv_live_now", {"channels": ["tv1", "tv3"]})).structured_content
    assert [c["channel"] for c in r["channels"]] == ["tv1", "tv3"]


async def test_live_search_program_episode(client):
    r = (await client.call_tool("tv_search", {"query": "پایتخت"})).structured_content
    assert any(p["program_id"] == PAYTAKHT for p in r["programs"])
    r = (await client.call_tool("tv_program", {"program_id": PAYTAKHT, "limit": 3})).structured_content
    assert r["title"] == "پایتخت 7" and r["episodes"]
    r = (await client.call_tool("tv_episode", {"episode_id": EPISODE})).structured_content
    assert r["title"] == "قسمت دوم پشت صحنه" and r["channel_id"] == "tv1" and r["minutes"] == 46


async def test_live_events(client):
    r = (await client.call_tool("tv_live_events", {})).structured_content
    assert "events" in r
