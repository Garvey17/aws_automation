"""AIDeploy CLI — main entry point.

Commands:
    aideploy init    — Detect FastAPI project and generate aideploy.yaml
    aideploy up      — Build and deploy FastAPI application to AWS
    aideploy down    — Safely destroy all AIDeploy-created resources
    aideploy status  — Display current deployment status and endpoints
    aideploy logs    — Tail or view application logs from CloudWatch
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aideploy.aws.client import get_aws_session, verify_credentials
from aideploy.aws.compute import get_app_runner_logs
from aideploy.config.loader import load_config, write_config
from aideploy.config.schema import AideployConfig, AppConfig, CostConfig, DeploymentConfig, HealthConfig, RuntimeConfig
from aideploy.constants import CONFIG_FILE, DEFAULT_HEALTH_PATH
from aideploy.deployment.deployer import Deployer
from aideploy.deployment.destroyer import destroy_deployment, plan_destruction
from aideploy.detector.fastapi import detect_project
from aideploy.docker.builder import write_dockerfile
from aideploy.exceptions import (
    AideployError,
    ConfigError,
    ConfigNotFoundError,
    StateNotFoundError,
)
from aideploy.state.manager import StateManager

app = typer.Typer(
    name="aideploy",
    help="Ephemeral AWS deployment CLI for FastAPI portfolio projects.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s" if debug else "%(message)s",
    )


@app.command()
def init(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing aideploy.yaml and Dockerfile."),
    ] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Enable verbose debug logging.")] = False,
) -> None:
    """Inspect the current directory, detect FastAPI, and generate aideploy.yaml."""
    setup_logging(debug)
    cwd = Path.cwd()
    config_file = cwd / CONFIG_FILE

    if config_file.exists() and not force:
        console.print(
            f"[yellow]Found existing {CONFIG_FILE}.[/yellow] Use [bold]--force[/bold] to overwrite.",
            style="yellow",
        )
        raise typer.Exit(code=1)

    project_info = detect_project(cwd)
    if project_info is None:
        console.print(
            "[red]FastAPI project not detected.[/red]\n"
            "AIDeploy requires a FastAPI application (with fastapi declared in requirements.txt or imported).",
            style="red",
        )
        raise typer.Exit(code=1)

    project_name = cwd.name.lower().replace(" ", "-").replace("_", "-")
    # Sanitise name to match schema: ^[a-zA-Z][a-zA-Z0-9_-]*$
    if not project_name[0].isalpha():
        project_name = f"app-{project_name}"

    entrypoint = project_info.entrypoint or "app.main:app"
    python_ver = project_info.python_version or "3.12"

    config = AideployConfig(
        name=project_name,
        runtime=RuntimeConfig(python=python_ver),
        app=AppConfig(entrypoint=entrypoint),
        health=HealthConfig(path=DEFAULT_HEALTH_PATH),
        environment=project_info.detected_env_vars,
        deployment=DeploymentConfig(strategy="auto"),
        cost=CostConfig(max_monthly=0),
    )

    write_config(config, cwd)
    _, dockerfile_created = write_dockerfile(config, cwd, force=force)

    console.print(f"[green]✓[/green] FastAPI project detected (Python {python_ver})")
    console.print(f"[green]✓[/green] Entrypoint set to [bold]{entrypoint}[/bold]")
    console.print(f"[green]✓[/green] Generated [bold]{CONFIG_FILE}[/bold]")
    if dockerfile_created:
        console.print("[green]✓[/green] Generated [bold]Dockerfile[/bold]")
    else:
        console.print("[blue]•[/blue] Kept existing [bold]Dockerfile[/bold]")

    if project_info.detected_env_vars:
        console.print(
            f"[blue]•[/blue] Detected environment variables: {', '.join(project_info.detected_env_vars)}"
        )

    console.print(
        "\n[bold green]Ready![/bold green] Next step: run [bold]aideploy up[/bold] to deploy."
    )


@app.command()
def up(
    profile: Annotated[
        Optional[str],
        typer.Option("--profile", "-p", help="AWS CLI profile to use for deployment."),
    ] = None,
    region: Annotated[
        Optional[str],
        typer.Option("--region", "-r", help="AWS region override."),
    ] = None,
    debug: Annotated[bool, typer.Option("--debug", help="Enable verbose debug logging.")] = False,
) -> None:
    """Build and deploy the FastAPI application to AWS App Runner."""
    setup_logging(debug)
    console.print("\n[bold cyan]AIDeploy[/bold cyan]\n")

    def on_progress(phase_index: int, total: int, phase_name: str, status: str) -> None:
        if status == "running":
            console.print(f"[{phase_index}/{total}] {phase_name:<30} ...", end="\r")
        elif status == "done":
            console.print(f"[{phase_index}/{total}] {phase_name:<30} [green]✓[/green]")

    deployer = Deployer(
        project_dir=Path.cwd(),
        profile=profile,
        region=region,
        progress_callback=on_progress,
    )

    try:
        result = deployer.run()
        console.print("\n[bold green]Deployment successful.[/bold green]\n")
        console.print(f"Endpoint:\n[bold underline blue]{result.endpoint}[/bold underline blue]\n")
    except AideployError as exc:
        console.print(f"\n[bold red]Deployment failed:[/bold red] {exc.message}")
        if exc.hint:
            console.print(f"\n[yellow]Hint:[/yellow] {exc.hint}")
        if debug:
            console.print_exception()
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {exc}")
        if debug:
            console.print_exception()
        raise typer.Exit(code=1)


@app.command()
def down(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
    profile: Annotated[
        Optional[str],
        typer.Option("--profile", "-p", help="AWS CLI profile."),
    ] = None,
    region: Annotated[
        Optional[str],
        typer.Option("--region", "-r", help="AWS region override."),
    ] = None,
    debug: Annotated[bool, typer.Option("--debug", help="Enable debug output.")] = False,
) -> None:
    """Safely destroy all AWS resources created by AIDeploy."""
    setup_logging(debug)

    try:
        state_mgr, state, resource_list = plan_destruction(Path.cwd())
    except StateNotFoundError:
        console.print("[yellow]No active deployment found (no .aideploy/state.json).[/yellow]")
        raise typer.Exit(code=0)
    except AideployError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"\nDeployment: [bold]{state.deployment_id}[/bold]")
    console.print(f"Project:    [bold]{state.project}[/bold]\n")
    console.print("[bold]Resources to destroy:[/bold]")
    for res in resource_list:
        console.print(f"  - {res}")
    console.print()

    if not yes:
        confirmed = typer.confirm("Continue with destruction?", default=False)
        if not confirmed:
            console.print("[yellow]Destruction cancelled.[/yellow]")
            raise typer.Exit(code=0)

    console.print("\n[cyan]Tearing down infrastructure...[/cyan]")

    def on_progress(msg: str) -> None:
        console.print(f"  [blue]•[/blue] {msg}")

    result = destroy_deployment(
        profile=profile,
        region=region,
        project_dir=Path.cwd(),
        progress_callback=on_progress,
    )

    if result.success:
        console.print("\n[bold green]✓ Cleanup complete. All AIDeploy resources destroyed.[/bold green]\n")
    else:
        console.print("\n[bold yellow]Cleanup completed with warnings:[/bold yellow]")
        for fail in result.failed_resources:
            console.print(f"  [red]✗[/red] {fail}")
        raise typer.Exit(code=1)


@app.command()
def status(
    debug: Annotated[bool, typer.Option("--debug", help="Enable debug output.")] = False,
) -> None:
    """Display current deployment status, endpoint, and resources."""
    setup_logging(debug)
    state_mgr = StateManager(Path.cwd())

    if not state_mgr.exists():
        console.print("Status: [bold yellow]NOT DEPLOYED[/bold yellow]")
        return

    try:
        state = state_mgr.load()
    except AideployError as exc:
        console.print(f"[red]Could not read state:[/red] {exc}")
        raise typer.Exit(code=1)

    status_color = "green" if state.status == "RUNNING" else "yellow"

    console.print(f"Project:       [bold]{state.project}[/bold]")
    console.print(f"Status:        [{status_color}]{state.status}[/{status_color}]")
    console.print(f"Deployment ID: {state.deployment_id}")
    console.print(f"Created:       {state.created_at}")
    console.print(f"Region:        {state.region or 'default'}")
    if state.endpoint:
        console.print(f"Endpoint:      [bold underline blue]{state.endpoint}[/bold underline blue]")
    else:
        console.print("Endpoint:      None")

    console.print("\nResources:")
    for res in state.resources:
        console.print(f" [green]✓[/green] {res.resource_type:<20} {res.name} ({res.identifier})")

    console.print(f"\nExpires:\n  {state.expires_at or 'Never'}\n")


@app.command()
def logs(
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Continuously poll for new logs."),
    ] = False,
    tail: Annotated[
        int,
        typer.Option("--tail", "-n", help="Number of log lines to show."),
    ] = 50,
    system: Annotated[
        bool,
        typer.Option("--system", help="Show App Runner service system logs instead of app logs."),
    ] = False,
    profile: Annotated[Optional[str], typer.Option("--profile", "-p", help="AWS CLI profile.")] = None,
    region: Annotated[Optional[str], typer.Option("--region", "-r", help="AWS region.")] = None,
    debug: Annotated[bool, typer.Option("--debug", help="Enable debug output.")] = False,
) -> None:
    """Fetch recent logs from AWS CloudWatch for the deployed application."""
    setup_logging(debug)
    state_mgr = StateManager(Path.cwd())

    if not state_mgr.exists():
        console.print("[yellow]No active deployment found. Run `aideploy up` first.[/yellow]")
        raise typer.Exit(code=1)

    state = state_mgr.load()
    app_runner_arn = None
    for r in state.resources:
        if r.resource_type == "apprunner_service":
            app_runner_arn = r.identifier
            break

    if not app_runner_arn:
        console.print("[yellow]No App Runner service found in deployment state.[/yellow]")
        raise typer.Exit(code=1)

    aws_session = get_aws_session(profile=profile, region=region or state.region)
    log_type = "service" if system else "application"

    console.print(f"[cyan]Fetching {log_type} logs for {state.project}...[/cyan]\n")

    seen_lines = set()
    try:
        while True:
            lines = get_app_runner_logs(
                session=aws_session,
                service_arn=app_runner_arn,
                log_type=log_type,
                limit=tail,
            )
            if not lines:
                if not follow:
                    console.print("[yellow]No log events found yet.[/yellow]")
                    break
            else:
                for line in lines:
                    if line not in seen_lines:
                        console.print(line)
                        seen_lines.add(line)

            if not follow:
                break
            time.sleep(3)
    except KeyboardInterrupt:
        console.print("\n[yellow]Log streaming stopped.[/yellow]")


def main() -> None:
    """Entrypoint function."""
    app()


if __name__ == "__main__":
    main()
