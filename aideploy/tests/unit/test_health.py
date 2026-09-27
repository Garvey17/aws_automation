"""Unit tests for application health check module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aideploy.config.schema import HealthConfig
from aideploy.deployment.health import check_health
from aideploy.exceptions import HealthCheckError


@pytest.mark.unit
class TestHealthCheck:
    """Tests for HTTP health check polling."""

    @patch("httpx.Client.get")
    def test_health_check_succeeds_immediately(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        config = HealthConfig(path="/health", timeout=5, retries=3, interval=1)
        res = check_health("https://example.com", config)
        assert res is True
        mock_get.assert_called_once_with("https://example.com/health")

    @patch("time.sleep")
    @patch("httpx.Client.get")
    def test_health_check_succeeds_after_retry(
        self,
        mock_get: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        fail_resp = MagicMock(status_code=503)
        ok_resp = MagicMock(status_code=200)
        mock_get.side_effect = [fail_resp, ok_resp]

        config = HealthConfig(path="/health", timeout=5, retries=3, interval=1)
        res = check_health("https://example.com", config)
        assert res is True
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    @patch("httpx.Client.get")
    def test_health_check_fails_after_exhaustion(
        self,
        mock_get: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        config = HealthConfig(path="/health", timeout=5, retries=3, interval=1)
        with pytest.raises(HealthCheckError):
            check_health("https://example.com", config)
        assert mock_get.call_count == 3
