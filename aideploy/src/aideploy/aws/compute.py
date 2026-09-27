"""AWS App Runner compute service management.

Handles creation, updating, polling, log retrieval, and deletion of App Runner services.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import boto3
import botocore.exceptions

from aideploy.aws.client import wrap_aws_errors
from aideploy.constants import (
    APP_RUNNER_CPU,
    APP_RUNNER_MEMORY,
    APP_RUNNER_PORT,
    DEFAULT_HEALTH_PATH,
    TAG_DEPLOYMENT_ID,
    TAG_ENVIRONMENT,
    TAG_ENVIRONMENT_VALUE,
    TAG_MANAGED_BY,
    TAG_MANAGED_BY_VALUE,
    TAG_PROJECT,
)
from aideploy.exceptions import AWSError, AWSTimeoutError, DeploymentError

logger = logging.getLogger(__name__)


def get_service_name(project_name: str) -> str:
    """Generate App Runner service name."""
    return f"aideploy-{project_name.lower()}"


def create_or_update_app_runner_service(
    session: boto3.Session,
    project_name: str,
    deployment_id: str,
    image_uri: str,
    access_role_arn: str,
    port: int = APP_RUNNER_PORT,
    health_path: str = DEFAULT_HEALTH_PATH,
    env_vars: dict[str, str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create or update an AWS App Runner service for the FastAPI application.

    Returns:
        dict containing 'service_arn', 'service_url', 'service_id', 'status'
    """
    apprunner = session.client("apprunner")
    service_name = get_service_name(project_name)
    tags = [
        {"Key": TAG_MANAGED_BY, "Value": TAG_MANAGED_BY_VALUE},
        {"Key": TAG_PROJECT, "Value": project_name},
        {"Key": TAG_DEPLOYMENT_ID, "Value": deployment_id},
        {"Key": TAG_ENVIRONMENT, "Value": TAG_ENVIRONMENT_VALUE},
    ]

    source_config: dict[str, Any] = {
        "ImageRepository": {
            "ImageIdentifier": image_uri,
            "ImageRepositoryType": "ECR",
            "ImageConfiguration": {
                "Port": str(port),
            },
        },
        "AuthenticationConfiguration": {
            "AccessRoleArn": access_role_arn,
        },
        "AutoDeploymentsEnabled": False,
    }

    if env_vars:
        source_config["ImageRepository"]["ImageConfiguration"][
            "RuntimeEnvironmentVariables"
        ] = env_vars

    instance_config = {
        "Cpu": APP_RUNNER_CPU,
        "Memory": APP_RUNNER_MEMORY,
    }

    health_check_config = {
        "Protocol": "HTTP",
        "Path": health_path,
        "Interval": 10,
        "Timeout": 5,
        "HealthyThreshold": 1,
        "UnhealthyThreshold": 5,
    }

    existing_service = _find_service_by_name(apprunner, service_name)

    with wrap_aws_errors("AppRunner CreateService/UpdateService", service_name):
        if existing_service:
            service_arn = existing_service["ServiceArn"]
            logger.info("Updating existing App Runner service: %s", service_name)
            if progress_callback:
                progress_callback(f"Updating existing App Runner service {service_name}...")

            resp = apprunner.update_service(
                ServiceArn=service_arn,
                SourceConfiguration=source_config,
                InstanceConfiguration=instance_config,
                HealthCheckConfiguration=health_check_config,
            )
            service_summary = resp["Service"]
        else:
            logger.info("Creating App Runner service: %s", service_name)
            if progress_callback:
                progress_callback(f"Creating App Runner service {service_name}...")

            resp = apprunner.create_service(
                ServiceName=service_name,
                SourceConfiguration=source_config,
                InstanceConfiguration=instance_config,
                HealthCheckConfiguration=health_check_config,
                Tags=tags,
            )
            service_summary = resp["Service"]

        service_arn = service_summary["ServiceArn"]
        service_id = service_summary.get("ServiceId", "")
        service_url = service_summary.get("ServiceUrl", "")

        return {
            "service_arn": service_arn,
            "service_id": service_id,
            "service_url": f"https://{service_url}" if service_url and not service_url.startswith("http") else service_url,
            "service_name": service_name,
            "status": service_summary.get("Status", "OPERATION_IN_PROGRESS"),
        }


def _find_service_by_name(apprunner_client: Any, service_name: str) -> dict[str, Any] | None:
    """Find active App Runner service matching name."""
    try:
        paginator = apprunner_client.get_paginator("list_services")
        for page in paginator.paginate():
            for summary in page.get("ServiceSummaryList", []):
                if summary.get("ServiceName") == service_name:
                    if summary.get("Status") != "DELETED":
                        return summary
    except botocore.exceptions.ClientError:
        pass
    return None


def wait_for_app_runner_service(
    session: boto3.Session,
    service_arn: str,
    max_wait_seconds: int = 600,
    poll_interval: int = 15,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Poll App Runner service until it reaches RUNNING or fails.

    Returns:
        Service description dictionary with 'ServiceUrl' and 'Status'.

    Raises:
        DeploymentError: If the service transitions to CREATE_FAILED or OPERATION_FAILED.
        AWSTimeoutError: If max_wait_seconds is exceeded.
    """
    apprunner = session.client("apprunner")
    start_time = time.time()
    last_status = None

    while (time.time() - start_time) < max_wait_seconds:
        with wrap_aws_errors("AppRunner DescribeService", service_arn):
            resp = apprunner.describe_service(ServiceArn=service_arn)
            service = resp["Service"]
            status = service.get("Status", "UNKNOWN")
            service_url = service.get("ServiceUrl", "")

            if status != last_status:
                logger.debug("App Runner status transition: %s -> %s", last_status, status)
                last_status = status
                if progress_callback:
                    progress_callback(f"App Runner status: {status}")

            if status == "RUNNING":
                full_url = f"https://{service_url}" if service_url and not service_url.startswith("http") else service_url
                service["ServiceUrl"] = full_url
                return service

            if status in ("CREATE_FAILED", "UPDATE_FAILED", "DELETED"):
                raise DeploymentError(
                    f"App Runner service deployment failed with status: {status}",
                    hint="Check `aideploy logs` or AWS CloudWatch logs for deployment errors.",
                )

            time.sleep(poll_interval)

    raise AWSTimeoutError(
        f"App Runner service {service_arn} did not become RUNNING within {max_wait_seconds}s.",
        hint="The AWS provisioning took longer than expected. Check service status via `aideploy status`.",
    )


def delete_app_runner_service(
    session: boto3.Session,
    service_arn: str | None = None,
    project_name: str | None = None,
    wait: bool = False,
) -> bool:
    """Delete the App Runner service.

    Returns:
        True if deleted or already gone.
    """
    apprunner = session.client("apprunner")

    if not service_arn and project_name:
        svc = _find_service_by_name(apprunner, get_service_name(project_name))
        if svc:
            service_arn = svc["ServiceArn"]

    if not service_arn:
        logger.debug("No App Runner service found to delete")
        return True

    with wrap_aws_errors("AppRunner DeleteService", service_arn):
        try:
            apprunner.delete_service(ServiceArn=service_arn)
            logger.info("Initiated deletion of App Runner service: %s", service_arn)

            if wait:
                # Wait until deleted
                for _ in range(30):
                    time.sleep(5)
                    try:
                        desc = apprunner.describe_service(ServiceArn=service_arn)
                        if desc["Service"].get("Status") == "DELETED":
                            break
                    except botocore.exceptions.ClientError as exc:
                        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                            break
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return True
            raise


def get_app_runner_logs(
    session: boto3.Session,
    service_arn: str,
    log_type: str = "application",  # 'application' or 'service'
    limit: int = 50,
) -> list[str]:
    """Fetch recent log events for an App Runner service from CloudWatch Logs.

    Returns:
        List of log message strings.
    """
    logs_client = session.client("logs")
    apprunner = session.client("apprunner")

    try:
        service_resp = apprunner.describe_service(ServiceArn=service_arn)
        service = service_resp["Service"]
        service_id = service.get("ServiceId")
        service_name = service.get("ServiceName")
    except Exception as exc:
        logger.warning("Could not describe App Runner service for logs: %s", exc)
        return []

    # App Runner CloudWatch log group naming convention:
    # /aws/apprunner/{service_name}/{service_id}/{log_type}
    log_group_name = f"/aws/apprunner/{service_name}/{service_id}/{log_type}"

    try:
        streams_resp = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy="LastEventTime",
            descending=True,
            limit=5,
        )
        streams = streams_resp.get("logStreams", [])
        if not streams:
            return []

        all_events: list[str] = []
        for stream in streams:
            stream_name = stream["logStreamName"]
            events_resp = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=stream_name,
                limit=limit,
                startFromHead=False,
            )
            for event in events_resp.get("events", []):
                all_events.append(event.get("message", "").rstrip())

        return all_events[-limit:]
    except botocore.exceptions.ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            logger.debug("Log group %s does not exist yet", log_group_name)
            return []
        logger.warning("Error fetching logs from %s: %s", log_group_name, exc)
        return []
