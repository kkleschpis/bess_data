import pandas as pd

from bess_pipeline.price_threshold_report import (
    PriceZone,
    annual_hours_below_threshold,
    country_price_frame,
    parse_entsoe_price_xml,
)


def test_country_threshold_hours_use_average_of_available_zones() -> None:
    prices = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC").tolist()
            * 2,
            "price_eur_per_mwh": [0.0, 20.0, 10.0, 0.0],
            "zone_code": ["A", "A", "B", "B"],
            "country_codes": [("DE",), ("DE",), ("DE",), ("DE",)],
        }
    )

    countries = country_price_frame(prices)
    result = annual_hours_below_threshold(
        countries,
        threshold=6.0,
        start_year=2024,
        end_year=2024,
        inclusive=False,
        column="country_name",
    )

    assert result.loc[2024, "Germany"] == 1.0


def test_threshold_hours_support_quarter_hour_prices() -> None:
    prices = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC"),
            "price_eur_per_mwh": [4.0, 4.0, 7.0, 4.0],
            "zone_code": ["AT"] * 4,
        }
    )

    result = annual_hours_below_threshold(
        prices,
        threshold=5.0,
        start_year=2024,
        end_year=2024,
        inclusive=False,
        column="zone_code",
    )

    assert result.loc[2024, "AT"] == 0.75


def test_parse_entsoe_price_xml_reads_period_points() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
      <TimeSeries>
        <currency_Unit.name>EUR</currency_Unit.name>
        <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
        <Period>
          <timeInterval>
            <start>2024-01-01T00:00Z</start>
            <end>2024-01-01T02:00Z</end>
          </timeInterval>
          <resolution>PT60M</resolution>
          <Point>
            <position>1</position>
            <price.amount>1.23</price.amount>
          </Point>
          <Point>
            <position>2</position>
            <price.amount>4.56</price.amount>
          </Point>
        </Period>
      </TimeSeries>
    </Publication_MarketDocument>
    """
    zone = PriceZone("TEST", "Test Zone", ("AT",), entsoe_eic="test")

    result = parse_entsoe_price_xml(xml, zone)

    assert list(result["price_eur_per_mwh"]) == [1.23, 4.56]
    assert list(result["timestamp_utc"]) == [
        pd.Timestamp("2024-01-01 00:00:00+0000", tz="UTC"),
        pd.Timestamp("2024-01-01 01:00:00+0000", tz="UTC"),
    ]
