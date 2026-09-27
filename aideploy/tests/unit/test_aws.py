"""Unit tests for AWS infrastructure modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

from aideploy.aws.client import get_aws_session, get_default_region, verify_credentials, wrap_aws_errors
from aideploy.aws.compute import (
    create_or_update_app_runner_service,
    delete_app_runner_service,
    get_app_runner_logs,
    wait_for_app_runner_service,
)
from aideploy.aws.iam import delete_app_runner_ecr_role, ensure_app_runner_ecr_role
from aideploy.aws.storage import delete_ecr_repository, ensure_ecr_repository, get_ecr_auth_token
from aideploy.exceptions import (
    AWSCredentialsError,
    AWSError,
    AWSPermissionError,
    AWSResourceNotFoundError,
    AWSTimeoutError,
    DeploymentError,
)


@pytest.mark.unit
class TestAWSClient:
    """Tests for AWS session resolution and credential verification."""

    def test_verify_credentials_success(self) -> None:
        session = MagicMock()
        sts = MagicMock()
        sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/developer",
            "UserId": "AIDA12345",
        }
        session.client.return_value = sts

        identity = verify_credentials(session)
        assert identity["account"] == "123456789012"
        assert identity["arn"] == "arn:aws:iam::123456789012:user/developer"

    def test_verify_credentials_no_credentials(self) -> None:
        session = MagicMock()
        sts = MagicMock()
        sts.get_caller_identity.side_effect = botocore.exceptions.NoCredentialsError()
        session.client.return_value = sts

        with pytest.raises(AWSCredentialsError):
            verify_credentials(session)

    def test_wrap_aws_errors_permission_denied(self) -> None:
        with pytest.raises(AWSPermissionError):
            with wrap_aws_errors("TestOp", "test-res"):
                raise botocore.exceptions.ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
                    "TestOp",
                )

    def test_wrap_aws_errors_not_found(self) -> None:
        with pytest.raises(AWSResourceNotFoundError):
            with wrap_aws_errors("TestOp", "test-res"):
                raise botocore.exceptions.ClientError(
                    {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
                    "TestOp",
                )


@pytest.mark.unit
class TestAWSIAM:
    """Tests for IAM role management."""

    def test_ensure_app_runner_ecr_role_creates_new(self) -> None:
        session = MagicMock()
        iam = MagicMock()
        iam.get_role.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "NoSuchEntity"}}, "GetRole"
        )
        iam.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/aideploy-test-role"}
        }
        session.client.return_value = iam

        arn = ensure_app_runner_ecr_role(session, "test-app", "dep-123")
        assert arn == "arn:aws:iam::123456789012:role/aideploy-test-role"
        iam.create_role.assert_called_once()
        iam.attach_role_policy.assert_called_once()

    def test_delete_app_runner_ecr_role(self) -> None:
        session = MagicMock()
        iam = MagicMock()
        session.client.return_value = iam

        assert delete_app_runner_ecr_role(session, "test-app") is True
        iam.detach_role_policy.assert_called_once()
        iam.delete_role.assert_called_once()


@pytest.mark.unit
class TestAWSStorage:
    """Tests for ECR repository operations."""

    def test_ensure_ecr_repository_creates_new(self) -> None:
        session = MagicMock()
        ecr = MagicMock()
        ecr.describe_repositories.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "RepositoryNotFoundException"}}, "DescribeRepositories"
        )
        ecr.create_repository.return_value = {
            "repository": {"repositoryUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/aideploy-test"}
        }
        session.client.return_value = ecr

        uri = ensure_ecr_repository(session, "test", "dep-123")
        assert "123456789012.dkr.ecr.us-east-1.amazonaws.com/aideploy-test" in uri
        ecr.create_repository.assert_called_once()
        ecr.put_lifecycle_policy.assert_called_once()

    def test_delete_ecr_repository(self) -> None:
        session = MagicMock()
        ecr = MagicMock()
        session.client.return_value = ecr

        assert delete_ecr_repository(session, "test") is True
        ecr.delete_repository.assert_called_once_with(repositoryName="aideploy-test", force=True)


@pytest.mark.unit
class TestAWSCompute:
    """Tests for App Runner compute operations."""

    def test_create_app_runner_service_new(self) -> None:
        session = MagicMock()
        apprunner = MagicMock()
        apprunner.get_paginator.return_value.paginate.return_value = [{"ServiceSummaryList": []}]
        apprunner.create_service.return_value = {
            "Service": {
                "ServiceArn": "arn:aws:apprunner:us-east-1:123:service/test/abc",
                "ServiceId": "abc",
                "ServiceUrl": "abc.us-east-1.awsapprunner.com",
                "Status": "OPERATION_IN_PROGRESS",
            }
        }
        session.client.return_value = apprunner

        res = create_or_update_app_runner_service(
            session=session,
            project_name="test",
            deployment_id="dep-123",
            image_uri="123.dkr.ecr.us-east-1.amazonaws.com/test:dep-123",
            access_role_arn="arn:aws:iam::123:role/test-role",
        )
        assert res["service_arn"] == "arn:aws:apprunner:us-east-1:123:service/test/abc"
        assert res["service_url"] == "https://abc.us-east-1.awsapprunner.com"

    def test_wait_for_app_runner_service_success(self) -> None:
        session = MagicMock()
        apprunner = MagicMock()
        apprunner.describe_service.return_value = {
            "Service": {
                "Status": "RUNNING",
                "ServiceUrl": "https://xyz.awsapprunner.com",
            }
        }
        session.client.return_value = apprunner

        service = wait_for_app_runner_service(session, "arn:aws:apprunner:us-east-1:123:service/test/abc", max_wait_seconds=5)
        assert service["Status"] == "RUNNING"

    def test_wait_for_app_runner_service_failed_status(self) -> None:
        session = MagicMock()
        apprunner = MagicMock()
        apprunner.describe_service.return_value = {
            "Service": {
                "Status": "CREATE_FAILED",
                "ServiceUrl": "",
            }
        }
        session.client.return_value = apprunner

        with pytest.raises(DeploymentError):
            wait_for_app_runner_service(session, "arn:aws:apprunner:us-east-1:123:service/test/abc", max_wait_seconds=5)
