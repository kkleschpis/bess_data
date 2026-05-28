from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from bess_pipeline.analytics import PRICE_ANALYTICS_TIMEZONE, price_daily_analytics
from bess_pipeline.config import DEFAULT_BIDDING_ZONES, DEFAULT_COUNTRIES
from bess_pipeline.fetch import fetch_all
from bess_pipeline.storage import processed_path, read_frame

st.set_page_config(page_title="BESS Data Pipeline", layout="wide")

COUNTRY_LABELS = {country.name: country.code for country in DEFAULT_COUNTRIES}
ZONE_LABELS = {zone.label: zone.code for zone in DEFAULT_BIDDING_ZONES}


@st.cache_data(show_spinner=False)
def load_dataset(name: str) -> pd.DataFrame:
    return read_frame(processed_path(name))


def filtered_by_country(frame: pd.DataFrame, country: str) -> pd.DataFrame:
    if frame.empty or "country" not in frame:
        return frame
    return frame[frame["country"] == country]


def filtered_by_zone(frame: pd.DataFrame, zone: str) -> pd.DataFrame:
    if frame.empty or "bidding_zone" not in frame:
        return frame
    return frame[frame["bidding_zone"] == zone]


def filtered_by_date_range(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if frame.empty:
        return frame
    filtered = frame.copy()
    if "timestamp_utc" in filtered:
        timestamps = pd.to_datetime(filtered["timestamp_utc"], utc=True)
        local_dates = timestamps.dt.tz_convert(PRICE_ANALYTICS_TIMEZONE).dt.date
        return filtered[(local_dates >= start) & (local_dates <= end)]
    if "date" in filtered:
        dates = pd.to_datetime(filtered["date"]).dt.date
        return filtered[(dates >= start) & (dates <= end)]
    return filtered


def format_metric(value: float, suffix: str) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.2f} {suffix}"


def show_empty_state(dataset: str) -> None:
    st.info(f"No cached {dataset} data yet. Fetch data from the sidebar to populate this view.")


st.title("BESS Data Pipeline")

with st.sidebar:
    st.header("Controls")
    selected_country_name = st.selectbox("Country", list(COUNTRY_LABELS), index=0)
    selected_zone_name = st.selectbox("Price zone", list(ZONE_LABELS), index=0)
    spread_hours = st.slider("Spread hours", min_value=1, max_value=12, value=4, step=1)
    today = date.today()
    start_date = st.date_input("Start", value=today - timedelta(days=1))
    end_date = st.date_input("End", value=today - timedelta(days=1))
    if st.button("Fetch selected range", type="primary"):
        if start_date > end_date:
            st.error("Start date must be before or equal to end date.")
        else:
            with st.spinner("Fetching Energy-Charts data..."):
                fetch_all(
                    start_date.isoformat(),
                    end_date.isoformat(),
                    country_codes=[COUNTRY_LABELS[selected_country_name]],
                    bidding_zone_codes=[ZONE_LABELS[selected_zone_name]],
                    spread_hours=spread_hours,
                )
                load_dataset.clear()
            st.success("Data updated.")

country = COUNTRY_LABELS[selected_country_name]
zone = ZONE_LABELS[selected_zone_name]

prices = filtered_by_date_range(
    filtered_by_zone(load_dataset("prices"), zone),
    start_date,
    end_date,
)
price_analytics = price_daily_analytics(prices, spread_hours)
production = filtered_by_country(load_dataset("production"), country)
forecasts = filtered_by_country(load_dataset("forecasts"), country)
ren_share = filtered_by_country(load_dataset("renewable_share_forecast"), country)
signal = filtered_by_country(load_dataset("signal"), country)
cbet = filtered_by_country(load_dataset("cross_border_trading"), country)
cbpf = filtered_by_country(load_dataset("cross_border_physical"), country)

metric_cols = st.columns(4)
metric_cols[0].metric("Price rows", f"{len(prices):,}")
metric_cols[1].metric("Production rows", f"{len(production):,}")
metric_cols[2].metric("Forecast rows", f"{len(forecasts):,}")
metric_cols[3].metric("Flow rows", f"{len(cbet) + len(cbpf):,}")

tab_price, tab_power, tab_forecasts, tab_flows = st.tabs(
    ["Prices", "Generation", "Forecasts & Signal", "Cross-Border"]
)

with tab_price:
    if prices.empty:
        show_empty_state("price")
    else:
        cumulative_negative = 0.0
        period_negative_avg = float("nan")
        if not price_analytics.empty:
            cumulative_negative = float(price_analytics["negative_price_hours"].sum())
            if cumulative_negative > 0:
                period_negative_avg = float(
                    (
                        price_analytics["negative_price_avg_eur_per_mwh"]
                        * price_analytics["negative_price_hours"]
                    ).sum()
                    / cumulative_negative
                )

        cols = st.columns(3)
        cols[0].metric(
            f"{spread_hours}h avg spread",
            format_metric(
                price_analytics["n_hour_spread_eur_per_mwh"].mean()
                if not price_analytics.empty
                else float("nan"),
                "EUR/MWh",
            ),
        )
        cols[1].metric("Cumulative negative hours", f"{cumulative_negative:g}")
        cols[2].metric("Avg negative price", format_metric(period_negative_avg, "EUR/MWh"))

        st.plotly_chart(
            px.line(prices, x="timestamp_utc", y="price_eur_per_mwh", color="bidding_zone"),
            use_container_width=True,
        )
        if not price_analytics.empty:
            st.plotly_chart(
                px.line(
                    price_analytics,
                    x="date",
                    y="n_hour_spread_eur_per_mwh",
                    color="bidding_zone",
                ),
                use_container_width=True,
            )
            st.plotly_chart(
                px.bar(
                    price_analytics,
                    x="date",
                    y="negative_price_hours",
                    color="bidding_zone",
                ),
                use_container_width=True,
            )
        license_info = prices["license_info"].dropna().unique()
        if len(license_info):
            st.caption(str(license_info[0]))

with tab_power:
    if production.empty:
        show_empty_state("generation")
    else:
        st.plotly_chart(
            px.area(
                production,
                x="timestamp_utc",
                y="power_gw",
                color="production_type",
                line_group="production_type",
            ),
            use_container_width=True,
        )

with tab_forecasts:
    if forecasts.empty:
        show_empty_state("forecast")
    else:
        st.plotly_chart(
            px.line(
                forecasts,
                x="timestamp_utc",
                y="forecast_value",
                color="production_type",
                line_dash="forecast_type",
            ),
            use_container_width=True,
        )

    cols = st.columns(2)
    with cols[0]:
        if not ren_share.empty:
            st.plotly_chart(
                px.line(
                    ren_share,
                    x="timestamp_utc",
                    y=["ren_share_pct", "solar_share_pct", "wind_onshore_share_pct"],
                ),
                use_container_width=True,
            )
    with cols[1]:
        if not signal.empty:
            st.plotly_chart(
                px.line(signal, x="timestamp_utc", y=["share_pct", "signal"]),
                use_container_width=True,
            )

with tab_flows:
    if cbet.empty and cbpf.empty:
        show_empty_state("cross-border")
    else:
        flow_frame = pd.concat([cbet, cbpf], ignore_index=True)
        st.plotly_chart(
            px.line(
                flow_frame,
                x="timestamp_utc",
                y="flow_gw",
                color="neighbor_country",
                line_dash="flow_type",
            ),
            use_container_width=True,
        )

st.caption(
    "Source: Energy-Charts.info. Unless stated otherwise by Energy-Charts, data is licensed "
    "under CC BY 4.0 and requires attribution. Review price endpoint license_info before "
    "external or commercial use."
)

if not Path("data/processed").exists():
    st.caption("No processed data directory exists yet.")
