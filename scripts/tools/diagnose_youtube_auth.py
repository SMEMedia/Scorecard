from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.sources.youtube import (  # noqa: E402
    ANALYTICS_API_URL,
    YOUTUBE_API_URL,
    authed_get_json,
    date_range_config,
    load_config,
    make_credentials,
)


def show(label: str, value: object) -> None:
    print(f"{label}: {value}")


def error_details(error: Exception) -> object:
    if isinstance(error, HTTPError):
        try:
            return error.read().decode("utf-8")
        except Exception:
            return repr(error)
    return repr(error)


def main() -> None:
    config, loaded_path, _ = load_config(ROOT / "config" / "sources" / "monthly" / "youtube.json")
    credentials = make_credentials(config)
    show("config", loaded_path)
    show("token_valid", credentials.valid)
    show("token_expired", credentials.expired)
    show("token_scopes", sorted(credentials.scopes or []))

    try:
        channels = authed_get_json(
            credentials,
            f"{YOUTUBE_API_URL}/channels",
            {"part": "id,snippet,statistics", "mine": "true"},
        )
        items = channels.get("items") or []
        show("channels.mine.count", len(items))
        for item in items:
            show(
                "channels.mine.item",
                {
                    "id": item.get("id"),
                    "title": item.get("snippet", {}).get("title"),
                    "subscriberCount": item.get("statistics", {}).get("subscriberCount"),
                },
            )
    except Exception as error:
        show("channels.mine.error", repr(error))

    try:
        playlists = authed_get_json(
            credentials,
            f"{YOUTUBE_API_URL}/playlists",
            {"part": "snippet", "mine": "true", "maxResults": 10},
        )
        items = playlists.get("items") or []
        show("playlists.mine.count", len(items))
        for item in items:
            show(
                "playlists.mine.item",
                {
                    "id": item.get("id"),
                    "title": item.get("snippet", {}).get("title"),
                    "channelTitle": item.get("snippet", {}).get("channelTitle"),
                },
            )
    except Exception as error:
        show("playlists.mine.error", error_details(error))

    playlist_id = None
    for report in config.get("reports", []):
        if report.get("playlist_id"):
            playlist_id = report["playlist_id"]
            break
    if playlist_id:
        try:
            playlist = authed_get_json(
                credentials,
                f"{YOUTUBE_API_URL}/playlists",
                {"part": "snippet", "id": playlist_id, "maxResults": 1},
            )
            items = playlist.get("items") or []
            show("configured_playlist.count", len(items))
            for item in items:
                show(
                    "configured_playlist.item",
                    {
                        "id": item.get("id"),
                        "title": item.get("snippet", {}).get("title"),
                        "channelId": item.get("snippet", {}).get("channelId"),
                        "channelTitle": item.get("snippet", {}).get("channelTitle"),
                    },
                )
        except Exception as error:
            show("configured_playlist.error", error_details(error))

    try:
        raw_range = date_range_config(config)
        analytics = authed_get_json(
            credentials,
            ANALYTICS_API_URL,
            {
                "ids": "channel==MINE",
                "startDate": raw_range["start_date"],
                "endDate": raw_range["end_date"],
                "metrics": "views",
            },
        )
        show("analytics.mine", json.dumps(analytics, indent=2))
    except Exception as error:
        show("analytics.mine.error", error_details(error))


if __name__ == "__main__":
    main()
