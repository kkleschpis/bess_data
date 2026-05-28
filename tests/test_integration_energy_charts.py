import os

import pytest

from bess_pipeline.client import EnergyChartsClient


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("BESS_RUN_INTEGRATION") != "1",
    reason="Set BESS_RUN_INTEGRATION=1 to call the live Energy-Charts API.",
)
def test_live_energy_charts_one_day_price_request() -> None:
    with EnergyChartsClient() as client:
        payload = client.get("/price", bzn="DE-LU", start="2026-05-01", end="2026-05-01")

    assert payload["unit"].replace(" ", "") == "EUR/MWh"
    assert payload["deprecated"] is False
    assert payload["price"]
