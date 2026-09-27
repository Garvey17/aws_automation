"""IAM management for AIDeploy.

Manages the IAM execution/access roles needed by AWS App Runner to pull images from ECR.
All created roles are tagged with AIDeploy metadata and safely destroyed upon teardown.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
import botocore.exceptions

from aideploy.aws.client import wrap_aws_errors
from aideploy.constants import (
    TAG_DEPLOYMENT_ID,
    TAG_ENVIRONMENT,
    TAG_ENVIRONMENT_VALUE,
    TAG_MANAGED_BY,
    TAG_MANAGED_BY_VALUE,
    TAG_PROJECT,
)
from aideploy.exceptions import AWSError

logger = logging.getLogger(__name__)

# AWS managed policy for App Runner to pull images from ECR
APP_RUNNER_ECR_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"

APPRUNNER_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "build.apprunner.amazonaws.com"
            },
            "Action": "sts:AssumeRole",
        }
    ],
}


def get_role_name(project_name: str) -> str:
    """Generate deterministic IAM role name for the project."""
    return f"aideploy-{project_name}-ecr-access-role"


def ensure_app_runner_ecr_role(
    session: boto3.Session,
    project_name: str,
    deployment_id: str,
) -> str:
    """Ensure IAM role exists for App Runner to pull images from ECR.

    Creates the role if missing, attaches the required AWSAppRunnerServicePolicyForECRAccess policy,
    tags it with AIDeploy identifiers, and returns the Role ARN.
    """
    iam = session.client("iam")
    role_name = get_role_name(project_name)
    tags = [
        {"Key": TAG_MANAGED_BY, "Value": TAG_MANAGED_BY_VALUE},
        {"Key": TAG_PROJECT, "Value": project_name},
        {"Key": TAG_DEPLOYMENT_ID, "Value": deployment_id},
        {"Key": TAG_ENVIRONMENT, "Value": TAG_ENVIRONMENT_VALUE},
    ]

    with wrap_aws_errors("IAM GetRole/CreateRole", role_name):
        try:
            response = iam.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
            logger.debug("Existing IAM role found: %s", role_arn)
            # Ensure tag updates
            try:
                iam.tag_role(RoleName=role_name, Tags=tags)
            except botocore.exceptions.ClientError:
                pass
            return str(role_arn)
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
                raise

        # Create role if it didn't exist
        logger.info("Creating IAM role %s for App Runner ECR access", role_name)
        create_resp = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(APPRUNNER_TRUST_POLICY),
            Description=f"AIDeploy managed role for {project_name} App Runner ECR access",
            Tags=tags,
        )
        role_arn = create_resp["Role"]["Arn"]

        # Attach policy
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn=APP_RUNNER_ECR_POLICY_ARN,
        )
        logger.debug("Attached %s to role %s", APP_RUNNER_ECR_POLICY_ARN, role_name)

        return str(role_arn)


def delete_app_runner_ecr_role(
    session: boto3.Session,
    project_name: str,
) -> bool:
    """Safely delete the IAM role for the project after detaching managed policies.

    Returns:
        True if deleted or already gone, False if deletion failed non-fatally.
    """
    iam = session.client("iam")
    role_name = get_role_name(project_name)

    with wrap_aws_errors("IAM DeleteRole", role_name):
        try:
            # Detach policy first
            try:
                iam.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn=APP_RUNNER_ECR_POLICY_ARN,
                )
                logger.debug("Detached policy %s from %s", APP_RUNNER_ECR_POLICY_ARN, role_name)
            except botocore.exceptions.ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in ("NoSuchEntity", "ResourceNotFoundException"):
                    logger.warning("Error detaching policy from %s: %s", role_name, exc)

            # Delete role
            iam.delete_role(RoleName=role_name)
            logger.info("Deleted IAM role %s", role_name)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchEntity":
                logger.debug("IAM role %s does not exist; nothing to delete", role_name)
                return True
            raise
