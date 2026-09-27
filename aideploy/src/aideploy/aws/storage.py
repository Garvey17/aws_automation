"""Amazon ECR storage management for AIDeploy.

Handles repository creation, lifecycle policy application, authentication token retrieval,
image pushing, and complete repository deletion.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from typing import Any

import boto3
import botocore.exceptions

from aideploy.aws.client import wrap_aws_errors
from aideploy.constants import (
    ECR_LIFECYCLE_KEEP_COUNT,
    TAG_DEPLOYMENT_ID,
    TAG_ENVIRONMENT,
    TAG_ENVIRONMENT_VALUE,
    TAG_MANAGED_BY,
    TAG_MANAGED_BY_VALUE,
    TAG_PROJECT,
)
from aideploy.exceptions import AWSError, DockerError

logger = logging.getLogger(__name__)


def get_repository_name(project_name: str) -> str:
    """Generate repository name for the project."""
    return f"aideploy-{project_name.lower()}"


def ensure_ecr_repository(
    session: boto3.Session,
    project_name: str,
    deployment_id: str,
) -> str:
    """Ensure ECR repository exists with lifecycle policy and tags.

    Returns:
        The ECR repository URI (e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/aideploy-my-api).
    """
    ecr = session.client("ecr")
    repo_name = get_repository_name(project_name)
    tags = [
        {"Key": TAG_MANAGED_BY, "Value": TAG_MANAGED_BY_VALUE},
        {"Key": TAG_PROJECT, "Value": project_name},
        {"Key": TAG_DEPLOYMENT_ID, "Value": deployment_id},
        {"Key": TAG_ENVIRONMENT, "Value": TAG_ENVIRONMENT_VALUE},
    ]

    with wrap_aws_errors("ECR DescribeRepositories/CreateRepository", repo_name):
        try:
            resp = ecr.describe_repositories(repositoryNames=[repo_name])
            repo = resp["repositories"][0]
            repo_uri = repo["repositoryUri"]
            logger.debug("Existing ECR repo found: %s", repo_uri)
            # Update tags
            try:
                ecr.tag_resource(resourceArn=repo["repositoryArn"], tags=tags)
            except botocore.exceptions.ClientError:
                pass
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "RepositoryNotFoundException":
                raise

            logger.info("Creating ECR repository %s", repo_name)
            create_resp = ecr.create_repository(
                repositoryName=repo_name,
                imageTagMutability="MUTABLE",
                imageScanningConfiguration={"scanOnPush": False},
                tags=tags,
            )
            repo = create_resp["repository"]
            repo_uri = repo["repositoryUri"]

        # Apply lifecycle policy to prune older images and prevent unbounded storage costs
        _apply_lifecycle_policy(ecr, repo_name)
        return str(repo_uri)


def _apply_lifecycle_policy(ecr_client: Any, repo_name: str) -> None:
    """Apply lifecycle policy to retain only the most recent images."""
    policy = {
        "rules": [
            {
                "rulePriority": 1,
                "description": f"Keep only last {ECR_LIFECYCLE_KEEP_COUNT} images",
                "selection": {
                    "tagStatus": "any",
                    "countType": "imageCountMoreThan",
                    "countNumber": ECR_LIFECYCLE_KEEP_COUNT,
                },
                "action": {"type": "expire"},
            }
        ]
    }
    try:
        ecr_client.put_lifecycle_policy(
            repositoryName=repo_name,
            lifecyclePolicyText=json.dumps(policy),
        )
        logger.debug("Applied ECR lifecycle policy to %s", repo_name)
    except botocore.exceptions.ClientError as exc:
        logger.warning("Could not set lifecycle policy on %s: %s", repo_name, exc)


def get_ecr_auth_token(session: boto3.Session) -> tuple[str, str, str]:
    """Retrieve ECR authorization token.

    Returns:
        tuple (username, password, registry_endpoint)
    """
    ecr = session.client("ecr")
    with wrap_aws_errors("ECR GetAuthorizationToken"):
        resp = ecr.get_authorization_token()
        auth_data = resp["authorizationData"][0]
        token = auth_data["authorizationToken"]
        decoded = base64.b64decode(token).decode("utf-8")
        username, password = decoded.split(":", 1)
        endpoint = auth_data["proxyEndpoint"]
        return username, password, endpoint


def push_image_to_ecr(
    session: boto3.Session,
    local_image_tag: str,
    ecr_repo_uri: str,
    deployment_id: str,
    progress_callback=None,
) -> str:
    """Tag local image with ECR URI and push it to AWS ECR.

    Returns:
        Full remote image URI (e.g. repo_uri:deployment_id).
    """
    remote_image_uri = f"{ecr_repo_uri}:{deployment_id}"

    # Tag local image to remote URI
    tag_cmd = ["docker", "tag", local_image_tag, remote_image_uri]
    logger.debug("Tagging image: %s -> %s", local_image_tag, remote_image_uri)
    try:
        tag_proc = subprocess.run(tag_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise DockerError(f"Failed to tag Docker image for ECR: {exc}") from exc

    # Authenticate Docker to ECR
    username, password, registry_endpoint = get_ecr_auth_token(session)
    login_cmd = ["docker", "login", "--username", username, "--password-stdin", registry_endpoint]
    try:
        login_proc = subprocess.run(
            login_cmd,
            input=password,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug("Docker login to ECR successful")
    except subprocess.CalledProcessError as exc:
        raise DockerError(
            f"Failed to authenticate Docker to ECR: {exc.stderr}",
            hint="Check AWS credentials and permissions for ecr:GetAuthorizationToken.",
        ) from exc

    # Push image to ECR
    push_cmd = ["docker", "push", remote_image_uri]
    logger.debug("Pushing image to ECR: %s", remote_image_uri)
    try:
        process = subprocess.Popen(
            push_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output_lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            output_lines.append(line)
            logger.debug("[docker push] %s", line)
            if progress_callback:
                progress_callback(line)

        process.wait()
        if process.returncode != 0:
            tail = "\n".join(output_lines[-20:])
            raise DockerError(
                f"Docker push to ECR failed (exit code {process.returncode}):\n{tail}",
                hint="Check ECR permissions and ensure repository exists.",
            )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise DockerError(f"Docker push failed: {exc}") from exc

    logger.info("Successfully pushed image to %s", remote_image_uri)
    return remote_image_uri


def delete_ecr_repository(
    session: boto3.Session,
    project_name: str,
) -> bool:
    """Delete ECR repository including all stored images.

    Returns:
        True if deleted or already gone.
    """
    ecr = session.client("ecr")
    repo_name = get_repository_name(project_name)

    with wrap_aws_errors("ECR DeleteRepository", repo_name):
        try:
            ecr.delete_repository(repositoryName=repo_name, force=True)
            logger.info("Deleted ECR repository %s", repo_name)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "RepositoryNotFoundException":
                logger.debug("ECR repository %s does not exist; nothing to delete", repo_name)
                return True
            raise
