"""Fetch the first BESS-focused Energy-Charts datasets."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import date, timedelta

import pandas as pd

from bess_pipeline.analytics import price_daily_analytics
from bess_pipeline.client import EnergyChartsClient
from bess_pipeline.config import (
    BIDDING_ZONES_BY_CODE,
    COUNTRIES_BY_CODE,
    DEFAULT_BIDDING_ZONES,
    DEFAULT_COUNTRIES,
    FORECAST_REQUESTS,
    BiddingZone,
    Country,
)
from bess_pipeline.storage import (
    append_or_replace_frame,
    ensure_data_dirs,
    processed_path,
    raw_path,
    read_frame,
    write_frame,
    write_json,
)
from bess_pipeline.transform import (
    cross_border_to_frame,
    forecast_to_frame,
    price_to_frame,
    production_to_frame,
    renewable_share_forecast_to_frame,
    signal_to_frame,
)


def _concat(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if not frame.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


def _fetch_with_raw(
    client: EnergyChartsClient,
    endpoint: str,
    label: str,
    start: str,
    end: str,
    **params: str,
) -> dict:
    payload = client.get(endpoint, start=start, end=end, **params)
    write_json(payload, raw_path(endpoint, label, start, end))
    return payload


def _fetch_optional_with_raw(
    client: EnergyChartsClient,
    endpoint: str,
    label: str,
    start: str,
    end: str,
    **params: str,
) -> dict | None:
    try:
        return _fetch_with_raw(client, endpoint, label, start, end, **params)
    except RuntimeError as exc:
        print(f"Skipping {endpoint} for {label}: {exc}")
        return None


def fetch_price_data(
    client: EnergyChartsClient,
    start: str,
    end: str,
    bidding_zones: Iterable[BiddingZone] = DEFAULT_BIDDING_ZONES,
) -> pd.DataFrame:
    frames = []
    for zone in bidding_zones:
        payload = _fetch_with_raw(client, "/price", zone.code, start, end, bzn=zone.code)
        frames.append(price_to_frame(payload, zone.code))
    return _concat(frames)


def fetch_country_data(
    client: EnergyChartsClient,
    start: str,
    end: str,
    countries: Iterable[Country] = DEFAULT_COUNTRIES,
) -> dict[str, pd.DataFrame]:
    production_frames = []
    forecast_frames = []
    ren_share_frames = []
    signal_frames = []
    cbet_frames = []
    cbpf_frames = []

    for country in countries:
        code = country.code
        public_power = _fetch_with_raw(client, "/public_power", code, start, end, country=code)
        production_frames.append(production_to_frame(public_power, code))

        for production_type, forecast_type in FORECAST_REQUESTS:
            label = f"{code}_{production_type}_{forecast_type}"
            forecast = _fetch_optional_with_raw(
                client,
                "/public_power_forecast",
                label,
                start,
                end,
                country=code,
                production_type=production_type,
                forecast_type=forecast_type,
            )
            if forecast is not None:
                forecast_frames.append(forecast_to_frame(forecast, code))

        ren_share = _fetch_optional_with_raw(
            client, "/ren_share_forecast", code, start, end, country=code
        )
        if ren_share is not None:
            ren_share_frames.append(renewable_share_forecast_to_frame(ren_share, code))

        signal = _fetch_optional_with_raw(client, "/signal", code, start, end, country=code)
        if signal is not None:
            signal_frames.append(signal_to_frame(signal, code))

        cbet = _fetch_optional_with_raw(client, "/cbet", code, start, end, country=code)
        if cbet is not None:
            cbet_frames.append(cross_border_to_frame(cbet, code, "trading"))

        cbpf = _fetch_optional_with_raw(client, "/cbpf", code, start, end, country=code)
        if cbpf is not None:
            cbpf_frames.append(cross_border_to_frame(cbpf, code, "physical"))

    return {
        "production": _concat(production_frames),
        "forecasts": _concat(forecast_frames),
        "renewable_share_forecast": _concat(ren_share_frames),
        "signal": _concat(signal_frames),
        "cross_border_trading": _concat(cbet_frames),
        "cross_border_physical": _concat(cbpf_frames),
    }


def fetch_all(
    start: str,
    end: str,
    country_codes: Iterable[str] | None = None,
    bidding_zone_codes: Iterable[str] | None = None,
    spread_hours: int = 4,
) -> dict[str, pd.DataFrame]:
    ensure_data_dirs()
    countries = _selected_countries(country_codes)
    bidding_zones = _selected_bidding_zones(bidding_zone_codes)
    with EnergyChartsClient() as client:
        frames = {"prices": fetch_price_data(client, start, end, bidding_zones)}
        frames.update(fetch_country_data(client, start, end, countries))

    for dataset, frame in frames.items():
        if frame.empty:
            continue
        append_or_replace_frame(frame, processed_path(dataset), keys=_dedupe_keys(dataset))

    cached_prices = read_frame(processed_path("prices"))
    if cached_prices.empty:
        cached_prices = frames["prices"]
    frames["price_daily_analytics"] = price_daily_analytics(cached_prices, spread_hours)
    if not frames["price_daily_analytics"].empty:
        _replace_price_analytics_for_n(frames["price_daily_analytics"], spread_hours)

    return frames


def _replace_price_analytics_for_n(frame: pd.DataFrame, spread_hours: int) -> None:
    path = processed_path("price_daily_analytics")
    if path.exists():
        existing = read_frame(path)
        existing = existing[existing["n_hours"] != spread_hours]
        frame = pd.concat([existing, frame], ignore_index=True)
    write_frame(frame, path)


def _selected_countries(country_codes: Iterable[str] | None) -> tuple[Country, ...]:
    if country_codes is None:
        return DEFAULT_COUNTRIES
    return tuple(COUNTRIES_BY_CODE[code] for code in country_codes)


def _selected_bidding_zones(bidding_zone_codes: Iterable[str] | None) -> tuple[BiddingZone, ...]:
    if bidding_zone_codes is None:
        return DEFAULT_BIDDING_ZONES
    return tuple(BIDDING_ZONES_BY_CODE[code] for code in bidding_zone_codes)


def _dedupe_keys(dataset: str) -> list[str]:
    common = {
        "prices": ["timestamp_utc", "bidding_zone"],
        "price_daily_analytics": ["date", "bidding_zone", "n_hours"],
        "production": ["timestamp_utc", "country", "production_type"],
        "forecasts": ["timestamp_utc", "country", "production_type", "forecast_type"],
        "renewable_share_forecast": ["timestamp_utc", "country"],
        "signal": ["timestamp_utc", "country"],
        "cross_border_trading": ["timestamp_utc", "country", "neighbor_country"],
        "cross_border_physical": ["timestamp_utc", "country", "neighbor_country"],
    }
    return common.get(dataset, [])


def default_start_end() -> tuple[str, str]:
    yesterday = date.today() - timedelta(days=1)
    return yesterday.isoformat(), yesterday.isoformat()


def parse_args() -> argparse.Namespace:
    start, end = default_start_end()
    parser = argparse.ArgumentParser(description="Fetch BESS-relevant Energy-Charts data.")
    parser.add_argument("--start", default=start, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", default=end, help="End date in YYYY-MM-DD format.")
    parser.add_argument(
        "--country",
        action="append",
        choices=sorted(COUNTRIES_BY_CODE),
        dest="countries",
        help="Country code to fetch. Repeat for multiple countries. Defaults to all.",
    )
    parser.add_argument(
        "--bidding-zone",
        action="append",
        choices=sorted(BIDDING_ZONES_BY_CODE),
        dest="bidding_zones",
        help="Price bidding zone to fetch. Repeat for multiple zones. Defaults to all.",
    )
    parser.add_argument(
        "--spread-hours",
        type=int,
        default=4,
        choices=range(1, 13),
        metavar="N",
        help="Number of highest and lowest price hours for daily spread analytics.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = fetch_all(args.start, args.end, args.countries, args.bidding_zones, args.spread_hours)
    for dataset, frame in frames.items():
        print(f"{dataset}: {len(frame):,} rows")


if __name__ == "__main__":
    main()
