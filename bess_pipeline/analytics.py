"""BESS-oriented analytics derived from normalized price data."""

from __future__ import annotations

import math

import pandas as pd

PRICE_ANALYTICS_COLUMNS = [
    "date",
    "bidding_zone",
    "n_hours",
    "low_price_avg_eur_per_mwh",
    "high_price_avg_eur_per_mwh",
    "n_hour_spread_eur_per_mwh",
    "negative_price_hours",
    "cumulative_negative_price_hours",
    "negative_price_avg_eur_per_mwh",
]
PRICE_ANALYTICS_TIMEZONE = "Europe/Berlin"


def price_daily_analytics(prices: pd.DataFrame, n_hours: int = 4) -> pd.DataFrame:
    """Calculate daily price spread and negative-price metrics by bidding zone."""
    _validate_n_hours(n_hours)
    if prices.empty:
        return pd.DataFrame(columns=PRICE_ANALYTICS_COLUMNS)

    frame = prices.copy()
    frame = frame.dropna(subset=["timestamp_utc", "price_eur_per_mwh", "bidding_zone"])
    if frame.empty:
        return pd.DataFrame(columns=PRICE_ANALYTICS_COLUMNS)

    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame["date"] = frame["timestamp_utc"].dt.tz_convert(PRICE_ANALYTICS_TIMEZONE).dt.date
    frame["interval_hours"] = _interval_hours(frame)

    rows = []
    group_keys = ["bidding_zone", "date"]
    for (bidding_zone, day), group in frame.groupby(group_keys, sort=True):
        low_avg = _weighted_edge_average(group, n_hours, ascending=True)
        high_avg = _weighted_edge_average(group, n_hours, ascending=False)
        negative = group[group["price_eur_per_mwh"] < 0]
        negative_hours = float(negative["interval_hours"].sum())
        negative_avg = _weighted_average(
            negative["price_eur_per_mwh"],
            negative["interval_hours"],
        )
        rows.append(
            {
                "date": day,
                "bidding_zone": bidding_zone,
                "n_hours": n_hours,
                "low_price_avg_eur_per_mwh": low_avg,
                "high_price_avg_eur_per_mwh": high_avg,
                "n_hour_spread_eur_per_mwh": high_avg - low_avg,
                "negative_price_hours": negative_hours,
                "negative_price_avg_eur_per_mwh": negative_avg,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=PRICE_ANALYTICS_COLUMNS)

    result = result.sort_values(["bidding_zone", "date", "n_hours"]).reset_index(drop=True)
    result["cumulative_negative_price_hours"] = result.groupby("bidding_zone")[
        "negative_price_hours"
    ].cumsum()
    return result[PRICE_ANALYTICS_COLUMNS]


def _validate_n_hours(n_hours: int) -> None:
    if n_hours < 1 or n_hours > 12:
        raise ValueError("n_hours must be between 1 and 12")


def _interval_hours(frame: pd.DataFrame) -> pd.Series:
    sorted_frame = frame.sort_values(["bidding_zone", "timestamp_utc"])
    deltas = sorted_frame.groupby("bidding_zone")["timestamp_utc"].diff(-1).abs()
    fallback = (
        deltas.dropna().dt.total_seconds().median() / 3600
        if not deltas.dropna().empty
        else 1.0
    )
    if math.isnan(fallback) or fallback <= 0:
        fallback = 1.0
    interval_hours = deltas.dt.total_seconds().div(3600).fillna(fallback)
    interval_hours = interval_hours.clip(lower=0, upper=1)
    return interval_hours.reindex(frame.index)


def _weighted_edge_average(group: pd.DataFrame, n_hours: int, ascending: bool) -> float:
    ranked = group.sort_values("price_eur_per_mwh", ascending=ascending)
    remaining = float(n_hours)
    weighted_sum = 0.0
    selected_hours = 0.0

    for row in ranked.itertuples(index=False):
        interval_hours = min(float(row.interval_hours), remaining)
        if interval_hours <= 0:
            continue
        weighted_sum += float(row.price_eur_per_mwh) * interval_hours
        selected_hours += interval_hours
        remaining -= interval_hours
        if remaining <= 0:
            break

    if selected_hours == 0:
        return float("nan")
    return weighted_sum / selected_hours


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    if values.empty or weights.empty or weights.sum() == 0:
        return float("nan")
    return float((values * weights).sum() / weights.sum())
