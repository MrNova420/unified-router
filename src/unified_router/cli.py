from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from .config import (
    load_config,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    PROVIDER_NAMES,
    PROVIDER_SIGNUP_URLS,
    detect_api_key,
)

app = typer.Typer(
    name="unified-router",
    help="Unified LLM API router - route requests across all free LLM providers",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def callback():
    pass


def _start_server(host: str, port: int, log_level: str):
    import uvicorn
    uvicorn.run(
        "unified_router.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
    )


@app.command()
def start(
    port: int = typer.Option(3333, "--port", "-p", help="Server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    log_level: str = typer.Option("info", "--log-level", "-l"),
):
    _start_server(host, port, log_level)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists() and not force:
        console.print("[yellow]Config already exists at ~/.config/unified-router/config.yml[/yellow]")
        console.print("Run with --force to overwrite")
        return

    console.print(Panel.fit(
        "[bold cyan]Unified Router — Setup Wizard[/bold cyan]\n"
        "Connect all your free LLM providers. We'll auto-detect any keys already in your environment.\n"
        "Press Enter to skip any provider you don't want to configure.",
        border_style="cyan",
    ))

    config = DEFAULT_CONFIG.copy()
    config["providers"] = {k: dict(v) for k, v in config["providers"].items()}

    for name, pcfg in config["providers"].items():
        display_name = PROVIDER_NAMES.get(name, name)
        signup_url = PROVIDER_SIGNUP_URLS.get(name, "")

        detected = detect_api_key(pcfg)

        console.print()
        console.print(f"[bold]{display_name}[/bold]")

        if pcfg.get("env_account_id"):
            from .config import detect_account_id
            current_acct = detect_account_id(pcfg) or ""
            acct_prompt = f"  Account ID [{current_acct}]: " if current_acct else "  Account ID (required): "
            acct = input(acct_prompt).strip()
            if not acct and current_acct:
                acct = current_acct
            if acct:
                config["providers"][name]["account_id"] = acct

        current_key = pcfg.get("api_key", "") or detected or ""
        key_prompt = f"  API key [{current_key[:16]}...]: " if current_key and len(current_key) > 16 else f"  API key [{current_key}]: " if current_key else f"  API key (or press Enter to skip): "

        if signup_url:
            console.print(f"  Get key at: [blue]{signup_url}[/blue]")

        key = input(key_prompt).strip()
        if not key and current_key:
            key = current_key

        if key:
            config["providers"][name]["api_key"] = key
            console.print(f"  [green][OK] {display_name} configured[/green]")
        else:
            console.print(f"  [dim][--] {display_name} skipped[/dim]")

    import yaml
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    console.print()
    console.print(Panel.fit(
        "[bold green][OK] Setup complete![/bold green]\n"
        f"Config saved to: {CONFIG_FILE}\n\n"
        "Run [bold]unified-router start[/bold] to start the server.",
        border_style="green",
    ))

    console.print()
    console.print("[bold]To use with OpenCode, add this to your opencode.jsonc:[/bold]")
    console.print()
    snippet = '''{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "unified-router": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Unified Router",
      "options": {
        "baseURL": "http://localhost:3333/v1"
      }
    }
  }
}'''
    console.print(Panel(snippet, border_style="blue", title="opencode.jsonc"))


@app.command()
def status():
    config = load_config()

    table = Table(title="Provider Status")
    table.add_column("Provider", style="cyan")
    table.add_column("API Key", style="white")
    table.add_column("Status", style="green")

    for name in config.get("priority", []):
        pcfg = config["providers"].get(name, {})
        display = PROVIDER_NAMES.get(name, name)
        key = pcfg.get("api_key", "")
        if key:
            key_display = key[:12] + "..." if len(key) > 12 else key
            key_cell = f"[green]{key_display}[/green]"
            status_cell = "[green][OK] Connected[/green]"
        else:
            key_cell = "[dim]none[/dim]"
            status_cell = "[dim]Not configured[/dim]"
        table.add_row(display, key_cell, status_cell)

    console.print(table)

    server = config.get("server", {})
    console.print(f"\n[bold]Server:[/bold] http://{server.get('host', '127.0.0.1')}:{server.get('port', 3333)}")
    console.print(f"\n[bold]Provider priority order:[/bold]")
    for i, name in enumerate(config.get("priority", []), 1):
        marker = "[green][OK][/green]" if config["providers"].get(name, {}).get("api_key") else "[dim][--][/dim]"
        console.print(f"  {i}. {marker} {PROVIDER_NAMES.get(name, name)}")


@app.command()
def config():
    config = load_config()
    print("Provider priority order:")
    for i, name in enumerate(config.get("priority", []), 1):
        pcfg = config["providers"].get(name, {})
        status = "[CONFIGURED]" if pcfg.get("api_key") else "[NOT CONFIGURED]"
        print(f"  {i}. {PROVIDER_NAMES.get(name, name)} {status}")

    print(f"\nServer: http://{config['server']['host']}:{config['server']['port']}")
    print(f"Config location: {CONFIG_FILE}")

    print("\nOpenCode integration snippet:")
    print('''{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "unified-router": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Unified Router",
      "options": {
        "baseURL": "http://localhost:3333/v1"
      }
    }
  }
}''')


@app.command()
def providers():
    config = load_config()
    table = Table(title="Available Providers & Models")
    table.add_column("Priority", style="dim")
    table.add_column("Provider", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("URL")

    for i, name in enumerate(config.get("priority", []), 1):
        pcfg = config["providers"].get(name, {})
        display = PROVIDER_NAMES.get(name, name)
        status = "[green][OK][/green]" if pcfg.get("api_key") else "[dim][--] Not configured[/dim]"
        url = PROVIDER_SIGNUP_URLS.get(name, "")
        table.add_row(str(i), display, status, url)

    console.print(table)


@app.command()
def health():
    async def _check():
        config = load_config()
        from .registry import build_providers
        providers = build_providers(config)

        if not providers:
            console.print("[red]No providers configured. Run 'unified-router init' first.[/red]")
            return

        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            table = Table(title="Provider Health Check")
            table.add_column("Provider", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Models", style="white")
            table.add_column("Latency", style="white")

            for name, prov in providers.items():
                import time
                display = PROVIDER_NAMES.get(name, name)
                start = time.time()
                try:
                    models = await prov.fetch_models(client)
                    latency = f"{(time.time() - start) * 1000:.0f}ms"
                    model_count = str(len(models))
                    status = "[green][OK] Online[/green]"
                except Exception as e:
                    latency = "-"
                    model_count = "-"
                    status = f"[red][ERR] {e!s}[/red]"
                table.add_row(display, status, model_count, latency)

            console.print(table)

    asyncio.run(_check())


@app.command()
def install_service():
    if sys.platform == "linux":
        unit = f"""[Unit]
Description=Unified LLM Router
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%i
ExecStart={sys.executable} -m unified_router start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
        path = Path.home() / ".config" / "systemd" / "user" / "unified-router.service"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit)
        console.print(f"[green]Service file created: {path}[/green]")
        console.print("Run these commands to enable and start:")
        console.print(f"  systemctl --user daemon-reload")
        console.print(f"  systemctl --user enable unified-router")
        console.print(f"  systemctl --user start unified-router")

    elif sys.platform == "darwin":
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unified-router</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>unified_router</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{Path.home()}</string>
</dict>
</plist>"""
        path = Path.home() / "Library" / "LaunchAgents" / "com.unified-router.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist_content)
        console.print(f"[green]LaunchAgent created: {path}[/green]")
        console.print("Run:")
        console.print(f"  launchctl load {path}")

    else:
        # Windows
        script_path = Path.home() / ".local" / "bin" / "unified-router-start.cmd"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(f"""@echo off
start /B "" "{sys.executable}" -m unified_router start
""")
        console.print(f"[green]Start script created: {script_path}[/green]")
        console.print("You can add this to your startup folder or Task Scheduler.")


def main():
    app()
