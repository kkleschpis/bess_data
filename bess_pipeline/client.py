"""Small Energy-Charts API client with polite defaults."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, HttpUrl

from bess_pipeline.config import ENERGY_CHARTS_BASE_URL


class EnergyChartsClientConfig(BaseModel):
    base_url: HttpUrl = Field(default=ENERGY_CHARTS_BASE_URL)
    timeout_seconds: float = 30.0
    max_retries: int = 5
    backoff_seconds: float = 2.0
    min_request_interval_seconds: float = 1.0


class EnergyChartsClient:
    """Thin wrapper around the public Energy-Charts REST API."""

    def __init__(self, config: EnergyChartsClientConfig | None = None) -> None:
        self.config = config or EnergyChartsClientConfig()
        self._last_request_at = 0.0
        self._client = httpx.Client(
            base_url=str(self.config.base_url).rstrip("/"),
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": "bess-data-pipeline/0.1"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EnergyChartsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get(self, endpoint: str, **params: str | int | bool | None) -> dict[str, Any]:
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                self._wait_for_request_slot()
                response = self._client.get(path, params=clean_params)
                if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    last_error = RuntimeError(_response_error_message(response))
                    self._sleep_after_rate_limit(response, attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected JSON object from {path}, got {type(payload)!r}")
                self._last_request_at = time.monotonic()
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt == self.config.max_retries:
                    break
                time.sleep(self.config.backoff_seconds * attempt)

        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(f"Energy-Charts request failed for {path}{detail}") from last_error

    def _wait_for_request_slot(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _sleep_after_rate_limit(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(retry_after) if retry_after else None
        except ValueError:
            wait_seconds = None
        if wait_seconds is None:
            wait_seconds = self.config.backoff_seconds * attempt * 2
        self._last_request_at = time.monotonic()
        time.sleep(wait_seconds)

    def build_url(self, endpoint: str, **params: str | int | bool | None) -> str:
        """Return the URL that would be requested; useful for tests and debugging."""
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return str(self._client.build_request("GET", path, params=clean_params).url)


def _response_error_message(response: httpx.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    if len(text) > 240:
        text = f"{text[:237]}..."
    if text:
        return f"HTTP {response.status_code} {response.reason_phrase}: {text}"
    return f"HTTP {response.status_code} {response.reason_phrase}"
