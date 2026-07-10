"""Channel-stats fetch: parses the Data API v3 payload into a KV snapshot, and no-ops safely
when OAuth is unconfigured. The v3 service is mocked — no network."""

from __future__ import annotations

from unittest.mock import MagicMock

from ai_operator.ops import channel_stats
from ai_operator.publisher import oauth_headless


class _Settings:
    def __init__(self, configured: bool):
        self._configured = configured

    def missing(self, keys):
        return [] if self._configured else list(keys)


def test_pull_channel_stats_parses_and_saves(temp_db, monkeypatch):
    monkeypatch.setattr(channel_stats, "settings", _Settings(True))
    svc = MagicMock()
    svc.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"statistics": {"subscriberCount": "1234", "viewCount": "56789", "videoCount": "12"}}]
    }
    monkeypatch.setattr(oauth_headless, "build_service", lambda: svc)

    out = channel_stats.pull_channel_stats()
    assert out == {"subscribers": 1234, "total_views": 56789, "video_count": 12, "fetched_at": out["fetched_at"]}

    loaded = channel_stats.load_channel_stats()
    assert loaded["subscribers"] == 1234 and loaded["video_count"] == 12 and "fetched_at" in loaded


def test_pull_channel_stats_noop_when_unconfigured(temp_db, monkeypatch):
    monkeypatch.setattr(channel_stats, "settings", _Settings(False))
    assert channel_stats.pull_channel_stats() is None
    assert channel_stats.load_channel_stats() is None


def test_hidden_subscriber_count_defaults_to_zero(temp_db, monkeypatch):
    monkeypatch.setattr(channel_stats, "settings", _Settings(True))
    svc = MagicMock()
    svc.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"statistics": {"viewCount": "10", "videoCount": "2"}}]  # subscriberCount hidden
    }
    monkeypatch.setattr(oauth_headless, "build_service", lambda: svc)
    out = channel_stats.pull_channel_stats()
    assert out["subscribers"] == 0 and out["total_views"] == 10
