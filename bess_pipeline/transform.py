"""Transform Energy-Charts JSON responses into tidy tables."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd


def timestamps_to_datetime(unix_seconds: Iterable[int] | None) -> pd.Series:
    values = list(unix_seconds or [])
    return pd.to_datetime(values, unit="s", utc=True)


def _meta_columns(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if value is not None}


def named_series_to_long(
    payload: dict[str, Any],
    series_key: str,
    value_name: str,
    name_column: str,
    **meta: Any,
) -> pd.DataFrame:
    timestamps = timestamps_to_datetime(payload.get("unix_seconds"))
    series = payload.get(series_key) or []
    rows: list[pd.DataFrame] = []

    for item in series:
        values = item.get("data") or []
        frame = pd.DataFrame(
            {
                "timestamp_utc": timestamps[: len(values)],
                name_column: item.get("name"),
                value_name: values,
            }
        )
        rows.append(frame)

    if not rows:
        return pd.DataFrame(
            columns=["timestamp_utc", name_column, value_name, *list(_meta_columns(meta))]
        )

    result = pd.concat(rows, ignore_index=True)
    for key, value in _meta_columns(meta).items():
        result[key] = value
    return result


def price_to_frame(payload: dict[str, Any], bidding_zone: str) -> pd.DataFrame:
    values = payload.get("price") or []
    timestamps = timestamps_to_datetime(payload.get("unix_seconds"))
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps[: len(values)],
            "price_eur_per_mwh": values,
            "bidding_zone": bidding_zone,
            "unit": payload.get("unit"),
            "license_info": payload.get("license_info"),
        }
    )


def production_to_frame(payload: dict[str, Any], country: str) -> pd.DataFrame:
    return named_series_to_long(
        payload,
        series_key="production_types",
        value_name="power_gw",
        name_column="production_type",
        country=country,
    )


def forecast_to_frame(payload: dict[str, Any], country: str) -> pd.DataFrame:
    values = payload.get("forecast_values") or []
    timestamps = timestamps_to_datetime(payload.get("unix_seconds"))
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps[: len(values)],
            "forecast_value": values,
            "country": country,
            "production_type": payload.get("production_type"),
            "forecast_type": payload.get("forecast_type"),
        }
    )


def renewable_share_forecast_to_frame(payload: dict[str, Any], country: str) -> pd.DataFrame:
    timestamps = timestamps_to_datetime(payload.get("unix_seconds"))
    data = {
        "timestamp_utc": timestamps,
        "country": country,
        "ren_share_pct": payload.get("ren_share") or [],
        "solar_share_pct": payload.get("solar_share") or [],
        "wind_onshore_share_pct": payload.get("wind_onshore_share") or [],
        "wind_offshore_share_pct": payload.get("wind_offshore_share") or [],
        "substitute": payload.get("substitute"),
    }
    return pd.DataFrame({key: pd.Series(value) for key, value in data.items()})


def signal_to_frame(payload: dict[str, Any], country: str) -> pd.DataFrame:
    share = payload.get("share") or []
    signal = payload.get("signal") or []
    timestamps = timestamps_to_datetime(payload.get("unix_seconds"))
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps[: len(share)],
            "country": country,
            "share_pct": share,
            "signal": signal[: len(share)],
            "substitute": payload.get("substitute"),
        }
    )


def cross_border_to_frame(payload: dict[str, Any], country: str, flow_type: str) -> pd.DataFrame:
    return named_series_to_long(
        payload,
        series_key="countries",
        value_name="flow_gw",
        name_column="neighbor_country",
        country=country,
        flow_type=flow_type,
    )
