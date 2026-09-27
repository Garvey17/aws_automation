"""Application health checker.

Verifies that the deployed public API endpoint is live and responding to HTTP health checks.
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urljoin

import httpx

from aideploy.config.schema import HealthConfig
from aideploy.exceptions import HealthCheckError

logger = logging.getLogger(__name__)


def check_health(
    base_url: str,
    health_config: HealthConfig,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> bool:
    """Poll the application health endpoint until healthy or retries exhausted.

    Args:
        base_url: Public base URL of the service (e.g. "https://xxx.awsapprunner.com").
        health_config: Validated health check configuration.
        progress_callback: Optional callable(attempt, max_attempts, status_message).

    Returns:
        True if the endpoint responds with 2xx status code.

    Raises:
        HealthCheckError: If health check fails after all retries.
    """
    clean_base = base_url.rstrip("/")
    clean_path = health_config.path.lstrip("/")
    health_url = f"{clean_base}/{clean_path}"

    retries = health_config.retries
    timeout = health_config.timeout
    interval = health_config.interval

    logger.info("Starting health check on %s (retries=%d, timeout=%ds)", health_url, retries, timeout)

    with httpx.Client(timeout=timeout, verify=True, follow_redirects=True) as client:
        for attempt in range(1, retries + 1):
            if progress_callback:
                progress_callback(attempt, retries, f"Attempt {attempt}/{retries}: checking {health_url}...")
            try:
                response = client.get(health_url)
                if 200 <= response.status_code < 300:
                    logger.info("Health check passed (status %d): %s", response.status_code, health_url)
                    return True
                else:
                    logger.debug(
                        "Health check returned status %d on attempt %d/%d",
                        response.status_code,
                        attempt,
                        retries,
                    )
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                logger.debug("Health check error on attempt %d/%d: %s", attempt, retries, exc)

            if attempt < retries:
                time.sleep(interval)

    raise HealthCheckError(health_url, retries)
