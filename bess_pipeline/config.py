"""Project defaults for the first BESS data slice."""

from __future__ import annotations

from dataclasses import dataclass

ENERGY_CHARTS_BASE_URL = "https://api.energy-charts.info"
RAW_DATA_DIR = "data/raw"
PROCESSED_DATA_DIR = "data/processed"


@dataclass(frozen=True)
class Country:
    code: str
    name: str


@dataclass(frozen=True)
class BiddingZone:
    code: str
    label: str
    country_code: str


DEFAULT_COUNTRIES: tuple[Country, ...] = (
    Country("de", "Germany"),
    Country("it", "Italy"),
    Country("es", "Spain"),
    Country("fr", "France"),
    Country("uk", "United Kingdom"),
)

DEFAULT_BIDDING_ZONES: tuple[BiddingZone, ...] = (
    BiddingZone("DE-LU", "Germany / Luxembourg", "de"),
    BiddingZone("FR", "France", "fr"),
    BiddingZone("ES", "Spain", "es"),
    BiddingZone("IT-North", "Italy North", "it"),
)

COUNTRIES_BY_CODE = {country.code: country for country in DEFAULT_COUNTRIES}
BIDDING_ZONES_BY_CODE = {zone.code: zone for zone in DEFAULT_BIDDING_ZONES}

FORECAST_REQUESTS: tuple[tuple[str, str], ...] = (
    ("load", "day-ahead"),
    ("solar", "current"),
    ("wind_onshore", "current"),
    ("wind_offshore", "current"),
)
