import pandas as pd

from bess_pipeline.analytics import price_daily_analytics
from bess_pipeline.transform import (
    cross_border_to_frame,
    price_to_frame,
    production_to_frame,
    timestamps_to_datetime,
)


def test_timestamps_to_datetime_returns_utc() -> None:
    result = timestamps_to_datetime([0, 3600])

    assert list(result) == [
        pd.Timestamp("1970-01-01 00:00:00+0000", tz="UTC"),
        pd.Timestamp("1970-01-01 01:00:00+0000", tz="UTC"),
    ]


def test_price_to_frame_handles_null_values() -> None:
    payload = {
        "unix_seconds": [0, 3600],
        "price": [50.0, None],
        "unit": "EUR/MWh",
        "license_info": "test license",
        "deprecated": False,
    }

    frame = price_to_frame(payload, "DE-LU")

    assert list(frame.columns) == [
        "timestamp_utc",
        "price_eur_per_mwh",
        "bidding_zone",
        "unit",
        "license_info",
    ]
    assert frame["price_eur_per_mwh"].isna().sum() == 1


def test_production_to_frame_converts_named_series_to_long() -> None:
    payload = {
        "unix_seconds": [0, 3600],
        "production_types": [
            {"name": "Solar", "data": [1.0, 2.0]},
            {"name": "Wind", "data": [3.0, None]},
        ],
        "deprecated": False,
    }

    frame = production_to_frame(payload, "de")

    assert len(frame) == 4
    assert set(frame["production_type"]) == {"Solar", "Wind"}
    assert set(frame["country"]) == {"de"}


def test_cross_border_to_frame_empty_payload_has_expected_columns() -> None:
    frame = cross_border_to_frame({"deprecated": False}, "de", "trading")

    assert frame.empty
    assert {"timestamp_utc", "neighbor_country", "flow_gw", "country", "flow_type"}.issubset(
        frame.columns
    )


def test_price_daily_analytics_calculates_top_bottom_average_spread() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC"),
            "bidding_zone": "DE-LU",
            "price_eur_per_mwh": [10.0, 20.0, 80.0, 100.0],
        }
    )

    result = price_daily_analytics(frame, n_hours=2)

    assert result.loc[0, "low_price_avg_eur_per_mwh"] == 15.0
    assert result.loc[0, "high_price_avg_eur_per_mwh"] == 90.0
    assert result.loc[0, "n_hour_spread_eur_per_mwh"] == 75.0


def test_price_daily_analytics_counts_negative_price_hours_cumulatively() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": [
                pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                pd.Timestamp("2026-01-01 01:00", tz="UTC"),
                pd.Timestamp("2026-01-02 00:00", tz="UTC"),
                pd.Timestamp("2026-01-02 01:00", tz="UTC"),
            ],
            "bidding_zone": "DE-LU",
            "price_eur_per_mwh": [-10.0, 5.0, -20.0, -40.0],
        }
    )

    result = price_daily_analytics(frame, n_hours=1)

    assert list(result["negative_price_hours"]) == [1.0, 2.0]
    assert list(result["cumulative_negative_price_hours"]) == [1.0, 3.0]
    assert result.loc[0, "negative_price_avg_eur_per_mwh"] == -10.0
    assert result.loc[1, "negative_price_avg_eur_per_mwh"] == -30.0


def test_price_daily_analytics_handles_no_negative_prices() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
            "bidding_zone": "DE-LU",
            "price_eur_per_mwh": [10.0, 20.0, 30.0],
        }
    )

    result = price_daily_analytics(frame, n_hours=1)

    assert result.loc[0, "negative_price_hours"] == 0.0
    assert pd.isna(result.loc[0, "negative_price_avg_eur_per_mwh"])


def test_price_daily_analytics_weights_quarter_hour_intervals() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC"),
            "bidding_zone": "DE-LU",
            "price_eur_per_mwh": [-10.0, -20.0, 10.0, 20.0, 30.0, 40.0, 90.0, 100.0],
        }
    )

    result = price_daily_analytics(frame, n_hours=1)

    assert result.loc[0, "negative_price_hours"] == 0.5
    assert result.loc[0, "low_price_avg_eur_per_mwh"] == 0.0
    assert result.loc[0, "high_price_avg_eur_per_mwh"] == 65.0


def test_price_daily_analytics_groups_by_european_market_day() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2026-04-30 22:00", periods=4, freq="15min", tz="UTC"),
            "bidding_zone": "DE-LU",
            "price_eur_per_mwh": [10.0, 20.0, 30.0, 40.0],
        }
    )

    result = price_daily_analytics(frame, n_hours=1)

    assert len(result) == 1
    assert str(result.loc[0, "date"]) == "2026-05-01"
