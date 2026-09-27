"""API Gateway management module for AIDeploy.

In V1, AWS App Runner provides direct managed TLS/HTTPS endpoints out of the box.
This module is structured for future architectures (e.g. Lambda container + HTTP API Gateway).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def format_endpoint_url(domain: str, protocol: str = "https") -> str:
    """Format and return a fully qualified HTTPS URL."""
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain
    return f"{protocol}://{domain}"
