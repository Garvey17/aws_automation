"""AWS client factory and credential management.

Provides standard AWS credential resolution, session caching, and unified
exception mapping for boto3 / botocore calls.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

import boto3
import botocore.exceptions

from aideploy.exceptions import (
    AWSCredentialsError,
    AWSError,
    AWSPermissionError,
    AWSResourceNotFoundError,
    AWSTimeoutError,
)

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_REGION = "us-east-1"


def get_aws_session(
    profile: str | None = None,
    region: str | None = None,
) -> boto3.Session:
    """Create a boto3 Session with optional profile and region overrides.

    Uses standard AWS credential resolution (env vars, ~/.aws/credentials, IAM role).

    Raises:
        AWSCredentialsError: If credentials or profile cannot be resolved.
    """
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        return session
    except botocore.exceptions.ProfileNotFound as exc:
        raise AWSCredentialsError(detail=f"AWS Profile '{profile}' was not found.") from exc
    except Exception as exc:
        raise AWSCredentialsError(detail=str(exc)) from exc


def get_default_region(session: boto3.Session | None = None) -> str:
    """Resolve the AWS region to use.

    Priority:
    1. Session region
    2. Default fallback ('us-east-1')
    """
    if session and session.region_name:
        return session.region_name
    sess = boto3.Session()
    return sess.region_name or DEFAULT_FALLBACK_REGION


def verify_credentials(session: boto3.Session) -> dict[str, str]:
    """Verify that valid AWS credentials are available via sts:GetCallerIdentity.

    Returns:
        dict with 'account', 'arn', 'user_id'

    Raises:
        AWSCredentialsError: If authentication fails.
        AWSError: If the STS call fails for another reason.
    """
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        return {
            "account": identity.get("Account", ""),
            "arn": identity.get("Arn", ""),
            "user_id": identity.get("UserId", ""),
        }
    except (
        botocore.exceptions.NoCredentialsError,
        botocore.exceptions.PartialCredentialsError,
        botocore.exceptions.CredentialRetrievalError,
    ) as exc:
        raise AWSCredentialsError(detail=str(exc)) from exc
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        if code in ("AuthFailure", "InvalidClientTokenId", "SignatureDoesNotMatch", "AccessDenied"):
            raise AWSCredentialsError(detail=f"{code}: {msg}") from exc
        raise AWSError(f"Failed to verify AWS credentials: {msg}") from exc
    except Exception as exc:
        raise AWSCredentialsError(detail=str(exc)) from exc


@contextmanager
def wrap_aws_errors(operation_name: str, resource_name: str = "*") -> Generator[None, None, None]:
    """Context manager to convert botocore exceptions to AIDeploy AWSError subclasses."""
    try:
        yield
    except botocore.exceptions.ClientError as exc:
        error_info = exc.response.get("Error", {})
        code = error_info.get("Code", "")
        message = error_info.get("Message", str(exc))

        if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
            raise AWSPermissionError(action=operation_name, resource=resource_name) from exc
        elif code in (
            "ResourceNotFoundException",
            "RepositoryNotFoundException",
            "NoSuchEntity",
            "NotFoundException",
        ):
            raise AWSResourceNotFoundError(f"{operation_name}: {message}") from exc
        elif code in ("RequestTimeout", "PriorRequestNotComplete"):
            raise AWSTimeoutError(f"{operation_name} timed out: {message}") from exc
        else:
            raise AWSError(f"{operation_name} failed [{code}]: {message}") from exc
    except botocore.exceptions.NoCredentialsError as exc:
        raise AWSCredentialsError(detail=str(exc)) from exc
    except botocore.exceptions.EndpointConnectionError as exc:
        raise AWSError(
            f"Cannot connect to AWS endpoint during {operation_name}: {exc}",
            hint="Check your internet connection and AWS region configuration.",
        ) from exc
    except (AWSError, AWSCredentialsError, AWSPermissionError):
        raise
    except Exception as exc:
        raise AWSError(f"Unexpected AWS error during {operation_name}: {exc}") from exc
