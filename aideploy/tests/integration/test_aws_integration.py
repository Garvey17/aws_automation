"""Real AWS Integration tests (isolated from normal unit tests).

Run explicitly with:
    pytest -m aws

Requires active AWS credentials with sufficient IAM permissions.
"""

from __future__ import annotations

import os
import pytest

from aideploy.aws.client import get_aws_session, verify_credentials
from aideploy.aws.iam import delete_app_runner_ecr_role, ensure_app_runner_ecr_role
from aideploy.aws.storage import delete_ecr_repository, ensure_ecr_repository


@pytest.mark.aws
class TestAWSRealIntegration:
    """Isolated integration tests communicating with live AWS APIs."""

    @pytest.fixture(autouse=True)
    def check_aws_enabled(self) -> None:
        if os.environ.get("AIDEPLOY_RUN_AWS_INTEGRATION") != "1":
            pytest.skip("AWS integration tests disabled. Set AIDEPLOY_RUN_AWS_INTEGRATION=1 to run.")

    def test_verify_caller_identity(self) -> None:
        session = get_aws_session()
        identity = verify_credentials(session)
        assert "account" in identity
        assert len(identity["account"]) == 12

    def test_ecr_lifecycle(self) -> None:
        session = get_aws_session()
        project = "aideploy-int-test"
        dep_id = "dep-int-test"
        try:
            uri = ensure_ecr_repository(session, project, dep_id)
            assert project in uri
        finally:
            delete_ecr_repository(session, project)
