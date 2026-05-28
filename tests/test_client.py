from bess_pipeline.client import EnergyChartsClient, EnergyChartsClientConfig


def test_build_url_filters_empty_params() -> None:
    config = EnergyChartsClientConfig(base_url="https://api.energy-charts.info")
    with EnergyChartsClient(config) as client:
        url = client.build_url("/price", bzn="DE-LU", start="2026-05-01", end="")

    assert url == "https://api.energy-charts.info/price?bzn=DE-LU&start=2026-05-01"
