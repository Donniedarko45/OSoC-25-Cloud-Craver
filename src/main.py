"""
Cloud Craver - Infrastructure Template Generator and Validator
Main entry point for the Cloud Craver application.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install

# --- Import Custom Modules ---
BASE_DIR = Path(__file__).resolve().parent
for subdir in ["state", "cost", "terraform"]:  # ✅ Added terraform
    sub_path = BASE_DIR / subdir
    if sub_path.exists() and str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

# Rich initialization
install(show_locals=True)
console = Console()

# App constants
APP_NAME = "cloudcraver"
APP_VERSION = "1.0.0"

# --- Logging Setup ---
def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, show_time=True, show_path=False, rich_tracebacks=True)
        ]
    )
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.getLogger().addHandler(file_handler)

# --- App Configuration ---
def get_application_config():
    home_dir = Path.home()
    app_data_dir = home_dir / f".{APP_NAME}"
    app_data_dir.mkdir(exist_ok=True)
    (app_data_dir / "plugins").mkdir(exist_ok=True)
    (app_data_dir / "cache").mkdir(exist_ok=True)
    (app_data_dir / "logs").mkdir(exist_ok=True)

    return {
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "data_dir": app_data_dir,
            "cache_dir": app_data_dir / "cache",
            "log_dir": app_data_dir / "logs"
        },
        "plugins": {
            "discovery": {
                "search_paths": [
                    "plugins",
                    str(app_data_dir / "plugins"),
                    "/usr/local/share/cloudcraver/plugins"
                ]
            },
            "loader": {
                "isolation": True,
                "temp_dir": str(app_data_dir / "cache" / "temp"),
                "max_size": 100 * 1024 * 1024
            },
            "security": {
                "enabled": True,
                "max_cpu_time": 30,
                "max_memory": 100 * 1024 * 1024,
                "network_access": False
            },
            "dependencies": {
                "strict_versioning": True,
                "auto_install": False
            },
            "marketplace": {
                "repositories": [
                    "https://plugins.cloudcraver.io/api",
                    "https://community.cloudcraver.io/api"
                ],
                "cache_ttl": 3600,
                "security_scanning": True
            },
            "versioning": {
                "auto_update": False,
                "check_interval": 86400
            }
        }
    }

# --- CloudCraverApp ---
class CloudCraverApp:
    def __init__(self):
        self.config = get_application_config()
        self.plugin_manager = None
        self.logger = logging.getLogger("cloudcraver")
        log_level = self.config.get("app", {}).get("log_level", "INFO")
        log_file = self.config["app"]["log_dir"] / "cloudcraver.log"
        setup_logging(log_level, str(log_file))
        self.logger.info(f"Starting {APP_NAME} v{APP_VERSION}")

    async def initialize_plugin_system(self):
        try:
            from terraform_validator.core import PluginManager
            self.plugin_manager = PluginManager(
                config=self.config["plugins"],
                data_dir=self.config["app"]["data_dir"],
                cache_dir=self.config["app"]["cache_dir"]
            )
            loaded = await self.plugin_manager.load_all_plugins()
            self.logger.info(f"Loaded {loaded} plugins")
        except ImportError as e:
            self.logger.warning(f"Plugin system not available: {e}")

    async def shutdown(self):
        self.logger.info("Shutting down Cloud Craver...")
        if self.plugin_manager:
            for name in list(self.plugin_manager.plugins):
                await self.plugin_manager.unload_plugin(name)

# --- Global App Singleton ---
app_instance: Optional[CloudCraverApp] = None
def get_app() -> CloudCraverApp:
    global app_instance
    if app_instance is None:
        app_instance = CloudCraverApp()
    return app_instance

# --- CLI Setup ---
@click.group(context_settings={"help_option_names": ["--help", "-h"]})
@click.version_option(version=APP_VERSION)
@click.option('--debug', is_flag=True)
@click.pass_context
def cli(ctx, debug):
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug

# --- CLI Commands ---
@cli.command()
@click.pass_context
def init(ctx):
    async def _init():
        app = get_app()
        await app.initialize_plugin_system()
        console.print("[green]\u2713 Initialization complete[/green]")
    asyncio.run(_init())

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def validate(ctx, path):
    from terraform_validator.validator_dir.validate import validate_directory
    try:
        result = validate_directory(path)
        console.print(f"[green]Validation successful[/green]: {result}")
    except Exception as e:
        console.print(f"[red]Validation failed:[/red] {e}")
        if ctx.obj.get("debug"):
            console.print_exception()

@cli.command()
@click.argument('message', default='Hello from Cloud Craver!')
def hello(message):
    console.print(f"[green]{message}[/green]")
    console.print(f"[cyan]Cloud Craver v{APP_VERSION} is working![/cyan]")

# --- STATE COMMANDS ---
@cli.group()
def state():
    """Manage Terraform state."""
    pass

@state.command()
@click.argument("provider", type=click.Choice(["s3", "azure", "gcs"]))
@click.argument("bucket")
@click.option("--region", help="Cloud region")
def configure_backend(provider, bucket, region):
    from state.backend import configure_remote_backend
    configure_remote_backend(provider, bucket, region)

@state.command()
@click.argument("workspace")
def create_workspace(workspace):
    from state.workspace import create_workspace
    create_workspace(workspace)

@state.command()
@click.argument("workspace")
def switch_workspace(workspace):
    from state.workspace import switch_workspace
    switch_workspace(workspace)

@state.command()
@click.argument("workspace")
def delete_workspace(workspace):
    from state.workspace import delete_workspace
    delete_workspace(workspace)

@state.command()
@click.argument("backend")
def migrate(backend):
    from state.migrate import migrate_state_backend
    migrate_state_backend(backend)

@state.command()
@click.argument("path")
def detect_drift(path):
    from state.drift import detect_state_drift
    detect_state_drift(path)

@state.command()
@click.argument("path")
def cleanup(path):
    from state.cleanup import cleanup_state_files
    cleanup_state_files(path)

@state.command()
@click.argument("env")
def use_environment(env):
    from state.environments import use_environment
    use_environment(env)

# --- COST COMMANDS ---
@cli.group()
def cost():
    """Manage infrastructure cost estimation and reporting."""
    pass

@cost.command("estimate")
@click.argument("provider", type=click.Choice(["aws", "azure", "gcp"]))
@click.option("--tfplan", required=True, help="Terraform plan file")
def estimate_cost(provider, tfplan):
    if provider == "aws":
        from cost.aws import estimate_aws_cost
        estimate_aws_cost(tfplan)
    elif provider == "azure":
        from cost.azure import estimate_azure_cost
        estimate_azure_cost(tfplan)
    elif provider == "gcp":
        from cost.gcp import estimate_gcp_cost
        estimate_gcp_cost(tfplan)

@cost.command()
@click.option("--usage-pattern", required=True, help="Usage pattern JSON file")
def optimize(usage_pattern):
    from cost.optimizer import suggest_optimizations
    suggest_optimizations(usage_pattern)

@cost.command()
@click.option("--tfplan", required=True, help="Terraform plan file")
def compare(tfplan):
    from cost.compare import compare_providers
    compare_providers(tfplan)

@cost.command()
@click.option("--tfplan", required=True, help="Terraform plan file")
def forecast(tfplan):
    from cost.forecast import forecast_costs
    forecast_costs(tfplan)

@cost.command()
@click.option("--output", required=True, help="Output file path for the report")
def report(output):
    from cost.report import generate_cost_report
    generate_cost_report(output)

# --- TERRAFORM COMMANDS ---
@cli.group()
def terraform():
    """Run Terraform-related commands."""
    pass

@terraform.command("plan-generate")
@click.option("--directory", default=".", help="Terraform configuration directory")
@click.option("--out-file", default="plan.out", help="Output JSON file name")
def generate_plan(directory, out_file):
    from terraform.plan import generate_terraform_plan_json
    generate_terraform_plan_json(directory, out_file)

# --- Entry Point ---
def main():
    def handle_signal(signum, frame):
        console.print("\n[yellow]Shutdown signal received[/yellow]")
        asyncio.run(get_app().shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        cli()
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        console.print_exception()
        sys.exit(1)

if __name__ == "__main__":
    main()
