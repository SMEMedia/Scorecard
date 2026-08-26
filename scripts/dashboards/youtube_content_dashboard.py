from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from scripts.sources import youtube  # noqa: E402


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "youtube.json"
CONTENT_TYPES = ["Shorts", "Videos", "Lives", "Podcasts"]
CONTENT_COLORS = {
    "Shorts": "#8f73ff",
    "Videos": "#48d921",
    "Lives": "#ffb000",
    "Podcasts": "#31b6ff",
}


def _iso_duration_seconds(value: str | None) -> int:
    if not value:
        return 0
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?"
        r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if not match:
        return 0
    parts = {key: int(raw or 0) for key, raw in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _report_rows(
    credentials: Any,
    start_date: date,
    end_date: date,
    *,
    dimensions: str,
    filters: str | None = None,
    sort: str | None = None,
) -> pd.DataFrame:
    rows: list[list[Any]] = []
    start_index = 1
    page_size = 200
    headers: list[str] = []

    while True:
        response = youtube.authed_get_json(
            credentials,
            youtube.ANALYTICS_API_URL,
            {
                "ids": "channel==MINE",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "metrics": "views,estimatedMinutesWatched,averageViewDuration",
                "dimensions": dimensions,
                "filters": filters,
                "sort": sort,
                "startIndex": start_index,
                "maxResults": page_size,
            },
        )
        if not headers:
            headers = [item["name"] for item in response.get("columnHeaders", [])]
        page_rows = response.get("rows") or []
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        start_index += page_size

    if not rows:
        return pd.DataFrame(columns=headers)

    return pd.DataFrame(rows, columns=headers)


def _content_type_rows(
    credentials: Any,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    raw_df = _report_rows(
        credentials,
        start_date,
        end_date,
        dimensions="day,creatorContentType",
        sort="day",
    )
    if raw_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "content_type",
                "views",
                "watch_minutes",
                "avg_view_duration_seconds",
                "videos",
            ]
        )

    df = raw_df.rename(
        columns={
            "day": "date",
            "creatorContentType": "raw_content_type",
            "estimatedMinutesWatched": "watch_minutes",
            "averageViewDuration": "avg_view_duration_seconds",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    df["views"] = pd.to_numeric(df["views"], errors="coerce").fillna(0).astype(int)
    df["watch_minutes"] = pd.to_numeric(df["watch_minutes"], errors="coerce").fillna(0.0)
    df["avg_view_duration_seconds"] = pd.to_numeric(
        df["avg_view_duration_seconds"], errors="coerce"
    ).fillna(0.0)
    df["content_type"] = df["raw_content_type"].map(
        {
            "SHORTS": "Shorts",
            "LIVE_STREAM": "Lives",
            "VIDEO_ON_DEMAND": "Videos",
        }
    ).fillna("Videos")
    df["videos"] = 0
    return df[
        [
            "date",
            "content_type",
            "views",
            "watch_minutes",
            "avg_view_duration_seconds",
            "videos",
        ]
    ]


def _playlist_daily_rows(
    credentials: Any,
    start_date: date,
    end_date: date,
    playlist_ids: list[str],
) -> pd.DataFrame:
    frames = []
    for playlist_id in playlist_ids:
        raw_df = _report_rows(
            credentials,
            start_date,
            end_date,
            dimensions="day",
            filters=f"playlist=={playlist_id}",
            sort="day",
        )
        if raw_df.empty:
            continue
        frames.append(raw_df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "content_type",
                "views",
                "watch_minutes",
                "avg_view_duration_seconds",
                "videos",
            ]
        )

    df = pd.concat(frames, ignore_index=True).rename(
        columns={
            "day": "date",
            "estimatedMinutesWatched": "watch_minutes",
            "averageViewDuration": "avg_view_duration_seconds",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    df["views"] = pd.to_numeric(df["views"], errors="coerce").fillna(0).astype(int)
    df["watch_minutes"] = pd.to_numeric(df["watch_minutes"], errors="coerce").fillna(0.0)
    df["avg_view_duration_seconds"] = pd.to_numeric(
        df["avg_view_duration_seconds"], errors="coerce"
    ).fillna(0.0)
    df["content_type"] = "Podcasts"
    df["videos"] = 0
    return (
        df.groupby(["date", "content_type"], as_index=False)
        .agg(
            views=("views", "sum"),
            watch_minutes=("watch_minutes", "sum"),
            avg_view_duration_seconds=("avg_view_duration_seconds", "mean"),
            videos=("videos", "sum"),
        )
        .sort_values("date")
    )


def _video_ids_daily_rows(
    credentials: Any,
    start_date: date,
    end_date: date,
    video_ids: list[str],
    content_type: str,
) -> pd.DataFrame:
    frames = []
    for chunk in _chunked(video_ids, 500):
        raw_df = _report_rows(
            credentials,
            start_date,
            end_date,
            dimensions="day",
            filters=f"video=={','.join(chunk)}",
            sort="day",
        )
        if raw_df.empty:
            continue
        frames.append(raw_df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "content_type",
                "views",
                "watch_minutes",
                "avg_view_duration_seconds",
            ]
        )

    df = pd.concat(frames, ignore_index=True).rename(
        columns={
            "day": "date",
            "estimatedMinutesWatched": "watch_minutes",
            "averageViewDuration": "avg_view_duration_seconds",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    df["views"] = pd.to_numeric(df["views"], errors="coerce").fillna(0).astype(int)
    df["watch_minutes"] = pd.to_numeric(df["watch_minutes"], errors="coerce").fillna(0.0)
    df["avg_view_duration_seconds"] = pd.to_numeric(
        df["avg_view_duration_seconds"], errors="coerce"
    ).fillna(0.0)
    df["content_type"] = content_type
    return (
        df.groupby(["date", "content_type"], as_index=False)
        .agg(
            views=("views", "sum"),
            watch_minutes=("watch_minutes", "sum"),
            avg_view_duration_seconds=("avg_view_duration_seconds", "mean"),
        )
        .sort_values("date")
    )


def _video_total_rows(
    credentials: Any,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    raw_df = _report_rows(
        credentials,
        start_date,
        end_date,
        dimensions="video",
        sort="-views",
    )
    if raw_df.empty:
        return pd.DataFrame(
            columns=[
                "video_id",
                "views",
                "watch_minutes",
                "avg_view_duration_seconds",
            ]
        )

    df = raw_df.rename(
        columns={
            "video": "video_id",
            "estimatedMinutesWatched": "watch_minutes",
            "averageViewDuration": "avg_view_duration_seconds",
        }
    )
    df["views"] = pd.to_numeric(df["views"], errors="coerce").fillna(0).astype(int)
    df["watch_minutes"] = pd.to_numeric(df["watch_minutes"], errors="coerce").fillna(0.0)
    df["avg_view_duration_seconds"] = pd.to_numeric(
        df["avg_view_duration_seconds"], errors="coerce"
    ).fillna(0.0)
    return df


def _complete_daily_frame(
    daily_df: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    date_index = pd.date_range(start_date, end_date, freq="D")
    scaffold = pd.MultiIndex.from_product(
        [date_index, CONTENT_TYPES],
        names=["date", "content_type"],
    ).to_frame(index=False)
    if daily_df.empty:
        merged = scaffold
        merged["views"] = 0
        merged["watch_minutes"] = 0.0
        merged["avg_view_duration_seconds"] = 0.0
        return merged

    return scaffold.merge(
        daily_df,
        on=["date", "content_type"],
        how="left",
    ).fillna(
        {
            "views": 0,
            "watch_minutes": 0.0,
            "avg_view_duration_seconds": 0.0,
        }
    )


def _podcast_playlist_ids(config: dict[str, Any]) -> list[str]:
    playlist_ids = []
    for report in config.get("reports", []):
        name = str(report.get("name", "")).casefold()
        column_names = " ".join(
            str(mapping.get("scorecard_column", ""))
            for mapping in report.get("scorecard_metrics", [])
        ).casefold()
        if "podcast" not in f"{name} {column_names}":
            continue
        playlist_id = report.get("playlist_id")
        if playlist_id:
            playlist_ids.append(str(playlist_id))
    return sorted(set(playlist_ids))


def _playlist_video_ids(credentials: Any, playlist_ids: list[str]) -> set[str]:
    video_ids: set[str] = set()
    for playlist_id in playlist_ids:
        page_token = None
        while True:
            response = youtube.authed_get_json(
                credentials,
                f"{youtube.YOUTUBE_API_URL}/playlistItems",
                {
                    "part": "contentDetails",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                    "pageToken": page_token,
                },
            )
            for item in response.get("items") or []:
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    video_ids.add(video_id)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return video_ids


def _video_metadata(credentials: Any, video_ids: list[str]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    if not video_ids:
        return pd.DataFrame(
            columns=[
                "video_id",
                "title",
                "published_at",
                "duration_seconds",
                "is_live",
            ]
        )
    for chunk in _chunked(video_ids, 50):
        response = youtube.authed_get_json(
            credentials,
            f"{youtube.YOUTUBE_API_URL}/videos",
            {
                "part": "snippet,contentDetails,liveStreamingDetails",
                "id": ",".join(chunk),
                "maxResults": 50,
            },
        )
        for item in response.get("items") or []:
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            records.append(
                {
                    "video_id": item.get("id"),
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "duration_seconds": _iso_duration_seconds(content.get("duration")),
                    "is_live": bool(item.get("liveStreamingDetails")),
                }
            )
    return pd.DataFrame(records)


def _classify_content(
    analytics_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    podcast_video_ids: set[str],
) -> pd.DataFrame:
    if analytics_df.empty:
        return analytics_df.assign(
            title=pd.Series(dtype="string"),
            duration_seconds=pd.Series(dtype="int"),
            is_live=pd.Series(dtype="bool"),
            content_type=pd.Series(dtype="string"),
        )

    df = analytics_df.merge(metadata_df, on="video_id", how="left")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    df["views"] = pd.to_numeric(df["views"], errors="coerce").fillna(0).astype(int)
    df["watch_minutes"] = pd.to_numeric(df["watch_minutes"], errors="coerce").fillna(0.0)
    df["avg_view_duration_seconds"] = pd.to_numeric(
        df["avg_view_duration_seconds"], errors="coerce"
    ).fillna(0.0)
    df["duration_seconds"] = pd.to_numeric(
        df["duration_seconds"], errors="coerce"
    ).fillna(0).astype(int)
    df["title"] = df["title"].fillna("Unknown video")
    df["is_live"] = df["is_live"].fillna(False).astype(bool)

    def classify(row: pd.Series) -> str:
        if row["video_id"] in podcast_video_ids:
            return "Podcasts"
        if row["is_live"]:
            return "Lives"
        if row["duration_seconds"] <= 60:
            return "Shorts"
        return "Videos"

    df["content_type"] = df.apply(classify, axis=1)
    return df


@st.cache_data(ttl=900, show_spinner=False)
def load_dashboard_data(
    config_path: str,
    start_date: date,
    end_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    config, loaded_path, used_example = youtube.load_config(config_path)
    if used_example:
        raise youtube.ConfigError(
            f"No YouTube config found. Copy {loaded_path} to {DEFAULT_CONFIG} and configure OAuth."
        )

    credentials = youtube.make_credentials(config)
    notes = [f"Loaded YouTube config from {loaded_path}."]

    playlist_ids = _podcast_playlist_ids(config)
    video_totals_df = _video_total_rows(credentials, start_date, end_date)

    if video_totals_df.empty:
        return pd.DataFrame(), pd.DataFrame(), notes + ["No YouTube Analytics rows returned."]

    podcast_video_ids = _playlist_video_ids(credentials, playlist_ids)
    metadata_df = _video_metadata(credentials, sorted(video_totals_df["video_id"].dropna().unique()))
    detail_df = _classify_content(video_totals_df, metadata_df, podcast_video_ids)

    daily_frames = []
    for content_type in CONTENT_TYPES:
        content_video_ids = sorted(
            detail_df.loc[detail_df["content_type"] == content_type, "video_id"]
            .dropna()
            .unique()
        )
        daily_frames.append(
            _video_ids_daily_rows(
                credentials,
                start_date,
                end_date,
                content_video_ids,
                content_type,
            )
        )
    daily_source_df = pd.concat(daily_frames, ignore_index=True)

    daily_df = (
        daily_source_df.groupby(["date", "content_type"], as_index=False)
        .agg(
            views=("views", "sum"),
            watch_minutes=("watch_minutes", "sum"),
            avg_view_duration_seconds=("avg_view_duration_seconds", "mean"),
        )
        .sort_values(["date", "content_type"])
    )
    daily_df = _complete_daily_frame(daily_df, start_date, end_date)

    notes.append(
        "Videos are classified with YouTube Data API metadata, then each content-type line is fetched with a YouTube Analytics day report filtered to that group's video IDs."
    )
    return daily_df, detail_df, notes


def _format_seconds(value: float) -> str:
    total_seconds = int(round(value))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _kpi_frame(detail_df: pd.DataFrame) -> pd.DataFrame:
    if detail_df.empty:
        return pd.DataFrame(
            columns=[
                "content_type",
                "views",
                "videos",
                "avg_views",
                "watch_hours",
                "avg_view_duration_seconds",
            ]
        )
    grouped = (
        detail_df.groupby("content_type", as_index=False)
        .agg(
            views=("views", "sum"),
            videos=("video_id", "nunique"),
            watch_minutes=("watch_minutes", "sum"),
            avg_view_duration_seconds=("avg_view_duration_seconds", "mean"),
        )
        .set_index("content_type")
        .reindex(CONTENT_TYPES, fill_value=0)
        .reset_index()
    )
    grouped["avg_views"] = grouped.apply(
        lambda row: row["views"] / row["videos"] if row["videos"] else 0,
        axis=1,
    )
    grouped["watch_hours"] = grouped["watch_minutes"] / 60
    return grouped


def _render_kpis(kpis: pd.DataFrame) -> None:
    columns = st.columns(4)
    for column, content_type in zip(columns, CONTENT_TYPES):
        row = kpis[kpis["content_type"] == content_type].iloc[0]
        with column:
            st.markdown(
                f"""
                <div class="kpi-card" style="border-left-color: {CONTENT_COLORS[content_type]}">
                    <div class="kpi-label">{content_type}</div>
                    <div class="kpi-value">{int(row["views"]):,}</div>
                    <div class="kpi-sub">Avg {row["avg_views"]:,.0f} views | {int(row["videos"]):,} videos</div>
                    <div class="kpi-sub">{row["watch_hours"]:,.1f} watch hours | {_format_seconds(row["avg_view_duration_seconds"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _line_chart(daily_df: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(daily_df)
        .mark_line(point=True, interpolate="monotone", strokeWidth=3)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("views:Q", title="Views"),
            color=alt.Color(
                "content_type:N",
                title="Content type",
                scale=alt.Scale(
                    domain=CONTENT_TYPES,
                    range=[CONTENT_COLORS[item] for item in CONTENT_TYPES],
                ),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("content_type:N", title="Content type"),
                alt.Tooltip("views:Q", title="Views", format=","),
                alt.Tooltip("watch_minutes:Q", title="Watch minutes", format=",.0f"),
                alt.Tooltip(
                    "avg_view_duration_seconds:Q",
                    title="Avg view duration sec",
                    format=",.0f",
                ),
            ],
        )
        .properties(height=430)
    )


def main() -> None:
    st.set_page_config(
        page_title="YouTube Content Dashboard",
        page_icon="YT",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.8rem; }
        .kpi-card {
            min-height: 142px;
            padding: 18px 18px 16px;
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-left: 5px solid;
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(30, 41, 59, 0.72), rgba(15, 23, 42, 0.72));
        }
        .kpi-label {
            color: #a6adb8;
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .kpi-value {
            margin-top: 0.45rem;
            color: #f8fafc;
            font-size: 2rem;
            font-weight: 850;
            line-height: 1;
        }
        .kpi-sub {
            margin-top: 0.55rem;
            color: #cbd5e1;
            font-size: 0.86rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("YouTube Content Dashboard")
    st.caption(
        "Live YouTube Analytics split by Shorts, Videos, Lives, and podcast playlist content."
    )

    with st.sidebar:
        st.header("Controls")
        today = date.today()
        default_start = today - timedelta(days=90)
        start_date = st.date_input("Start date", value=default_start)
        end_date = st.date_input("End date", value=today - timedelta(days=1))
        config_path = st.text_input("YouTube config", value=str(DEFAULT_CONFIG))
        refresh = st.button("Refresh data", type="primary")
        if refresh:
            load_dashboard_data.clear()

    if start_date > end_date:
        st.error("Start date must be on or before end date.")
        return

    try:
        with st.spinner("Fetching YouTube Analytics..."):
            daily_df, detail_df, notes = load_dashboard_data(
                str(config_path),
                start_date,
                end_date,
            )
    except Exception as error:  # noqa: BLE001
        st.error(str(error))
        st.stop()

    if daily_df.empty or detail_df.empty:
        st.warning("No YouTube Analytics data was returned for this date range.")
        for note in notes:
            st.info(note)
        return

    kpis = _kpi_frame(detail_df)
    _render_kpis(kpis)

    st.subheader("Views Over Time")
    st.altair_chart(_line_chart(daily_df), use_container_width=True)

    left, right = st.columns([0.58, 0.42])
    with left:
        st.subheader("Content Type Summary")
        summary = kpis.copy()
        summary["Avg view duration"] = summary["avg_view_duration_seconds"].map(_format_seconds)
        summary = summary[
            [
                "content_type",
                "views",
                "videos",
                "avg_views",
                "watch_hours",
                "Avg view duration",
            ]
        ].rename(
            columns={
                "content_type": "Content type",
                "views": "Views",
                "videos": "Videos",
                "avg_views": "Avg views",
                "watch_hours": "Watch hours",
            }
        )
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Views": st.column_config.NumberColumn(format="%d"),
                "Videos": st.column_config.NumberColumn(format="%d"),
                "Avg views": st.column_config.NumberColumn(format="%.0f"),
                "Watch hours": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    with right:
        st.subheader("Top Videos")
        top_videos = (
            detail_df.groupby(["video_id", "title", "content_type"], as_index=False)
            .agg(views=("views", "sum"), watch_minutes=("watch_minutes", "sum"))
            .sort_values("views", ascending=False)
            .head(15)
            .rename(
                columns={
                    "title": "Title",
                    "content_type": "Content type",
                    "views": "Views",
                    "watch_minutes": "Watch minutes",
                }
            )
        )
        st.dataframe(
            top_videos[["Title", "Content type", "Views", "Watch minutes"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Views": st.column_config.NumberColumn(format="%d"),
                "Watch minutes": st.column_config.NumberColumn(format="%.0f"),
            },
        )

    with st.expander("Source notes"):
        for note in notes:
            st.write(note)


if __name__ == "__main__":
    main()
