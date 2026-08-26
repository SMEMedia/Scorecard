from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from scripts.lib.google_sheets_data import (  # noqa: E402
    get_values,
    make_credentials,
    make_credentials_from_info,
)


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"
CADENCE_TABS = {"Monthly": "Monthly Media Data", "Weekly": "Weekly Media Data"}
COLORS = ["#00A6A6", "#F59E0B", "#5B8FF9", "#E8684A", "#6DC8EC", "#9270CA"]

METRIC_GROUPS = {
    "Audience": [
        "AM Users", "AM New Users", "AM Return Users", "App Users",
        "Email Subscribers", "Facebook Followers", "YouTube Subscribers",
        "LinkedIn Followers", "X Followers", "Instagram Followers", "Threads Followers",
    ],
    "Traffic": [
        "AM Sessions", "AM Page Views", "App Sessions", "App Views",
        "eEdition Visits", "eEdition Users", "eEdition Page Views",
    ],
    "Content": [
        "Podcast Downloads", "YouTube Podcast Plays", "AM Web Podcast Plays",
        "Podcast Total", "YouTube Video Plays",
    ],
    "Search": [
        "Search Clicks", "Search Impressions", "Ave Search Position", "Search CTR",
    ],
    "Email": [
        "Emails Delivered", "Email Opens", "Email Open Rate", "Email Clicks",
        "Email CTR", "Email Click to Open Rate", "Email Starts", "Email Stops", "Email Net Subs",
    ],
    "Revenue": [
        "New IOs (Count)", "New IOs (Revenue)", "Rev / IO", "Pipeline Total",
        "Pipeline Total (Tv)",
    ],
}

DEFAULT_KPIS = {
    "Monthly": ["AM Users", "AM Sessions", "AM Page Views", "Podcast Total", "Emails Delivered", "New IOs (Revenue)"],
    "Weekly": ["AM Users", "AM Sessions", "AM Page Views", "Podcast Total", "Emails Delivered", "New IOs (Revenue)"],
}

SOCIAL_FOLLOWER_METRICS = [
    "Facebook Followers",
    "YouTube Subscribers",
    "LinkedIn Followers",
    "X Followers",
    "Instagram Followers",
    "Threads Followers",
]

LINKEDIN_PERFORMANCE_METRICS = [
    "LinkedIn Impressions (Organic)",
    "LinkedIn Impressions (Paid)",
    "LinkedIn Reach",
    "LinkedIn Clicks (Oragnic)",
    "LinkedIn Clicks (Paid)",
    "LinkedIn Reactions (Organic)",
    "LinkedIn Reactions (Paid)",
    "LinkenIn Comments (Organic)",
    "LinkenIn Comments (Paid)",
    "LinkedIn Reposts (Organic)",
    "LinkedIn Reposts (Paid)",
    "LinkedIn Engagement Rate (Organic)",
    "LinkedIn Engagement Rate (Paid)",
    "LinkedIn Posts",
]


def _secret(name: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(name, default)
    except FileNotFoundError:
        return default


def _connection_settings(config_path: str) -> tuple[str, str | dict[str, Any]]:
    path = Path(config_path)
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    google = config.get("google_sheet", {})
    spreadsheet_id = str(_secret("spreadsheet_id", google.get("spreadsheet_id", "")))
    inline_credentials = _secret("google_service_account")
    if inline_credentials:
        return spreadsheet_id, dict(inline_credentials)
    credentials_path = str(
        _secret("google_service_account_file", google.get("service_account_file", ""))
    )
    if not spreadsheet_id or not credentials_path:
        raise ValueError("Configure spreadsheet_id and google_service_account_file in config/scorecard.json or .streamlit/secrets.toml.")
    return spreadsheet_id, credentials_path


def _parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw or raw.casefold() in {"n/a", "na", "none", "-"}:
        return None
    is_percent = raw.endswith("%")
    cleaned = re.sub(r"[$,%\s]", "", raw).replace("(", "-").replace(")", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number / 100 if is_percent else number


def rows_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    headers = [str(value).strip() or f"Column {index + 1}" for index, value in enumerate(rows[0])]
    width = len(headers)
    body = [(list(row) + [None] * width)[:width] for row in rows[1:]]
    frame = pd.DataFrame(body, columns=headers).dropna(how="all")
    if frame.empty:
        return frame
    date_column = headers[0]
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    frame = frame.dropna(subset=[date_column]).sort_values(date_column)
    for column in headers[1:]:
        frame[column] = frame[column].map(_parse_number)
    return frame.reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def load_scorecard(config_path: str) -> dict[str, pd.DataFrame]:
    spreadsheet_id, credentials_config = _connection_settings(config_path)
    if isinstance(credentials_config, dict):
        credentials = make_credentials_from_info(credentials_config)
    else:
        credentials = make_credentials(credentials_config)
    tabs = [*CADENCE_TABS.values(), "Monthly Media Detail", "Monthly Engagement"]
    return {
        tab: rows_to_frame(get_values(credentials, spreadsheet_id, tab))
        for tab in tabs
    }


def _format_value(metric: str, value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    if "Rate" in metric or metric.endswith("CTR") or metric.endswith("%%") or metric.endswith("(%)"):
        return f"{value:.1%}"
    if "Revenue" in metric or metric == "Rev / IO" or metric.endswith("(Tv)"):
        return f"${value:,.0f}"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"


def _delta(current: float | None, previous: float | None) -> str | None:
    if current is None or previous in (None, 0) or pd.isna(current) or pd.isna(previous):
        return None
    return f"{(current / previous - 1):+.1%} vs prior period"


def _period_label(cadence: str, value: Any) -> str:
    period = pd.Timestamp(value)
    if cadence == "Weekly":
        return f"Week ending {period:%B} {period.day}, {period.year}"
    return f"Month of {period:%B %Y}"


def _available_metrics(frame: pd.DataFrame) -> list[str]:
    return [column for column in frame.columns[1:] if frame[column].notna().any()]


def _trend_chart(frame: pd.DataFrame, date_column: str, metrics: list[str]) -> alt.Chart:
    long = frame[[date_column, *metrics]].melt(date_column, var_name="Metric", value_name="Value").dropna()
    return (
        alt.Chart(long)
        .mark_line(point=alt.OverlayMarkDef(size=55), strokeWidth=2.5)
        .encode(
            x=alt.X(f"{date_column}:T", title=None),
            y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("Metric:N", scale=alt.Scale(range=COLORS)),
            tooltip=[alt.Tooltip(f"{date_column}:T", title="Period"), "Metric:N", alt.Tooltip("Value:Q", format=",.2f")],
        )
        .properties(height=390)
    )


def _period_change_table(frame: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    records = []
    for metric in metrics:
        series = frame[metric].dropna()
        current = series.iloc[-1] if len(series) else None
        previous = series.iloc[-2] if len(series) > 1 else None
        change = (current / previous - 1) if previous not in (None, 0) else None
        records.append({"Metric": metric, "Current": current, "Previous": previous, "Change": change})
    return pd.DataFrame(records)


def _render_kpis(frame: pd.DataFrame, metrics: list[str]) -> None:
    current = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame) > 1 else None
    for start in range(0, len(metrics), 3):
        columns = st.columns(3)
        for container, metric in zip(columns, metrics[start:start + 3]):
            old = previous.get(metric) if previous is not None else None
            container.metric(metric, _format_value(metric, current.get(metric)), _delta(current.get(metric), old))


def _render_change_table(changes: pd.DataFrame) -> None:
    st.dataframe(
        changes,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Metric": st.column_config.TextColumn(width="large"),
            "Current": st.column_config.NumberColumn(format="localized", width="small"),
            "Previous": st.column_config.NumberColumn(format="localized", width="small"),
            "Change": st.column_config.NumberColumn(format="percent", width="small"),
        },
    )


def _render_group(
    frame: pd.DataFrame,
    date_column: str,
    group: str,
    candidates: list[str],
    *,
    stacked: bool = False,
) -> None:
    metrics = [metric for metric in candidates if metric in frame and frame[metric].notna().any()]
    if not metrics:
        st.info(f"No {group.lower()} data is populated for the selected range.")
        return
    changes = _period_change_table(frame, metrics)
    if stacked:
        st.altair_chart(_trend_chart(frame, date_column, metrics[:6]), use_container_width=True)
        _render_change_table(changes)
        return

    left, right = st.columns([0.64, 0.36])
    with left:
        st.altair_chart(_trend_chart(frame, date_column, metrics[:6]), use_container_width=True)
    with right:
        _render_change_table(changes)


def _render_supporting_tab(frame: pd.DataFrame, title: str) -> None:
    st.subheader(title)
    if frame.empty:
        st.info("This Google Sheet tab has no dated rows.")
        return
    date_column = frame.columns[0]
    metrics = _available_metrics(frame)
    selected = st.multiselect(f"Metrics for {title}", metrics, default=metrics[:4], key=title)
    if selected:
        st.altair_chart(_trend_chart(frame, date_column, selected), use_container_width=True)
    st.dataframe(frame.sort_values(date_column, ascending=False), hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Media Performance Scorecard", page_icon="📊", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.4rem; max-width: 1500px;}
        [data-testid="stMetric"] {
            background: rgba(128, 128, 128, 0.09);
            border: 1px solid rgba(128, 128, 128, 0.22);
            border-radius: 12px;
            padding: 16px;
            color: inherit;
        }
        [data-testid="stMetricLabel"] {font-weight: 700;}
        [data-testid="stMetricLabel"] p,
        [data-testid="stMetricValue"] {color: inherit;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Media Performance Scorecard")
    st.caption("A unified view of audience, traffic, content, search, email, and commercial performance from the shared Google Scorecard.")

    with st.sidebar:
        st.header("Dashboard controls")
        cadence = st.radio("Reporting cadence", list(CADENCE_TABS), horizontal=True)
        if st.button("Refresh Google Sheet", type="primary", use_container_width=True):
            load_scorecard.clear()

    try:
        with st.spinner("Loading the Google Scorecard…"):
            datasets = load_scorecard(str(DEFAULT_CONFIG))
    except Exception as error:  # noqa: BLE001
        st.error(f"Could not load the Google Scorecard: {error}")
        st.info("Confirm the service-account JSON exists and that its email address has Viewer access to the sheet.")
        st.stop()

    source = datasets[CADENCE_TABS[cadence]]
    if source.empty:
        st.warning(f"{CADENCE_TABS[cadence]} has no dated rows.")
        st.stop()
    date_column = source.columns[0]
    minimum, maximum = source[date_column].min().date(), source[date_column].max().date()

    with st.sidebar:
        selected_dates = st.date_input("Date range", value=(minimum, maximum), min_value=minimum, max_value=maximum)
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date, end_date = minimum, maximum
    frame = source[source[date_column].dt.date.between(start_date, end_date)].copy()
    if frame.empty:
        st.warning("No scorecard periods fall inside that date range.")
        st.stop()

    available = _available_metrics(frame)
    defaults = [metric for metric in DEFAULT_KPIS[cadence] if metric in available][:6]
    with st.sidebar:
        kpis = st.multiselect("Headline KPIs (up to 6)", available, default=defaults, max_selections=6)
        st.caption(f"Latest data: {_period_label(cadence, frame[date_column].max())}")

    overview, channels, social, detail, engagement, quality = st.tabs(
        ["Executive overview", "Channel performance", "Social media", "Media detail", "Engagement", "Data quality"]
    )
    with overview:
        latest_period = frame[date_column].iloc[-1]
        st.subheader(_period_label(cadence, latest_period))
        if len(frame) > 1:
            previous_period = frame[date_column].iloc[-2]
            st.caption(f"Changes shown against {_period_label(cadence, previous_period).lower()}.")
        if kpis:
            _render_kpis(frame, kpis)
        st.subheader("Performance trends")
        trend_defaults = kpis[:4] or available[:4]
        trend_metrics = st.multiselect("Compare metrics", available, default=trend_defaults, max_selections=6)
        if trend_metrics:
            st.altair_chart(_trend_chart(frame, date_column, trend_metrics), use_container_width=True)
        st.subheader("Latest period scorecard")
        latest_changes = _period_change_table(frame, available)
        st.dataframe(
            latest_changes,
            hide_index=True,
            use_container_width=True,
            column_config={"Change": st.column_config.NumberColumn(format="percent")},
        )

    with channels:
        group_names = [name for name, metrics in METRIC_GROUPS.items() if any(metric in available for metric in metrics)]
        selected_group = st.segmented_control("Performance area", group_names, default=group_names[0])
        _render_group(frame, date_column, selected_group, METRIC_GROUPS[selected_group])

    with social:
        monthly_social = datasets["Monthly Media Data"].copy()
        social_date_column = monthly_social.columns[0]
        monthly_social = monthly_social[
            monthly_social[social_date_column].dt.date.between(start_date, end_date)
        ]
        if monthly_social.empty:
            st.info("No monthly social-media periods fall inside the selected date range.")
        else:
            follower_metrics = [
                metric
                for metric in SOCIAL_FOLLOWER_METRICS
                if metric in monthly_social and monthly_social[metric].notna().any()
            ]
            st.subheader(_period_label("Monthly", monthly_social[social_date_column].iloc[-1]))
            st.caption("Social audience totals and month-over-month changes across owned platforms.")
            if follower_metrics:
                _render_kpis(monthly_social, follower_metrics)
                st.subheader("Follower trends")
                st.altair_chart(
                    _trend_chart(monthly_social, social_date_column, follower_metrics),
                    use_container_width=True,
                )
            else:
                st.info("No social follower metrics are populated for this date range.")

            linkedin = datasets["Monthly Media Detail"].copy()
            linkedin_date_column = linkedin.columns[0]
            linkedin = linkedin[
                linkedin[linkedin_date_column].dt.date.between(start_date, end_date)
            ]
            linkedin_metrics = [
                metric
                for metric in LINKEDIN_PERFORMANCE_METRICS
                if metric in linkedin and linkedin[metric].notna().any()
            ]
            st.subheader("LinkedIn performance")
            if linkedin.empty or not linkedin_metrics:
                st.info("No LinkedIn performance metrics are populated for this date range.")
            else:
                _render_group(
                    linkedin,
                    linkedin_date_column,
                    "LinkedIn",
                    linkedin_metrics,
                    stacked=True,
                )

    with detail:
        if cadence == "Monthly":
            _render_supporting_tab(datasets["Monthly Media Detail"], "Acquisition and LinkedIn detail")
        else:
            st.info("The detailed acquisition and LinkedIn scorecard is reported monthly. Switch to Monthly to align it with the overview.")

    with engagement:
        if cadence == "Monthly":
            _render_supporting_tab(datasets["Monthly Engagement"], "Audience engagement")
        else:
            st.info("The engagement scorecard is reported monthly. Switch to Monthly to align it with the overview.")

    with quality:
        populated = frame[available].notna().mean().sort_values()
        q1, q2, q3 = st.columns(3)
        q1.metric("Periods in view", f"{len(frame):,}")
        q2.metric("Metrics populated", f"{len(available):,}")
        q3.metric("Overall completeness", f"{frame[available].notna().mean().mean():.1%}")
        quality_frame = populated.rename_axis("Metric").reset_index(name="Completeness")
        st.dataframe(
            quality_frame,
            hide_index=True,
            use_container_width=True,
            column_config={"Completeness": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
        )
        with st.expander("Raw scorecard data"):
            st.dataframe(frame.sort_values(date_column, ascending=False), hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
