from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import (
    load_config,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    detect_api_key,
    detect_account_id,
    get_provider_info,
)
from .registry import load_registry

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
    auto: bool = typer.Option(False, "--auto", "-a", help="Only use env-detected keys, skip interactive prompts"),
):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists() and not force:
        console.print("[yellow]Config already exists at ~/.config/unified-router/config.yml[/yellow]")
        console.print("Run with --force to overwrite")
        return

    console.print(Panel.fit(
        "[bold cyan]Unified Router - Setup Wizard[/bold cyan]\n"
        "Connect all your free LLM providers. We'll auto-detect any keys already in your environment.\n"
        "Press Enter to skip any provider you don't want to configure.",
        border_style="cyan",
    ))

    registry = load_registry()
    config = DEFAULT_CONFIG.copy()
    config["priority"] = list(DEFAULT_CONFIG["priority"])
    config["providers"] = {k: dict(v) for k, v in DEFAULT_CONFIG["providers"].items()}

    configured_count = 0
    auto_detected_count = 0

    # Collect all providers in priority order
    all_providers: list[tuple[str, dict, str]] = []
    for section_name, section_key in [("openai_compatible", "OpenAI Compatible"), ("custom", "Custom API")]:
        for name, reg in registry.get(section_name, {}).items():
            all_providers.append((name, reg, section_key))

    for name, reg, section_key in all_providers:
        display_name = reg.get("name", name)
        signup_url = reg.get("signup_url", "")

        pcfg = config["providers"].get(name, {})
        detected = detect_api_key(pcfg)
        current_key = pcfg.get("api_key", "") or detected or ""

        needs_account = bool(reg.get("env_account_id"))

        if needs_account:
            current_acct = detect_account_id(pcfg) or ""

        if current_key and needs_account and current_acct:
            config["providers"][name]["api_key"] = current_key
            config["providers"][name]["account_id"] = current_acct
            auto_detected_count += 1
            configured_count += 1
            continue

        if current_key and not needs_account:
            config["providers"][name]["api_key"] = current_key
            auto_detected_count += 1
            configured_count += 1
            continue

        if auto:
            continue

        console.print()
        console.print(f"[bold]{display_name}[/bold] [dim]({section_key})[/dim]")

        if needs_account:
            current_acct_val = detect_account_id(pcfg) or ""
            if not current_acct_val:
                acct_prompt = f"  Account ID (required): "
            else:
                acct_prompt = f"  Account ID [{current_acct_val}]: "
            acct = input(acct_prompt).strip()
            if not acct and current_acct_val:
                acct = current_acct_val
            if acct:
                config["providers"][name]["account_id"] = acct
            else:
                console.print(f"  [dim][--] {display_name} skipped (no account ID)[/dim]")
                continue

        if signup_url:
            console.print(f"  Get key at: [blue]{signup_url}[/blue]")

        key = input(f"  API key (or press Enter to skip): ").strip()

        if key:
            config["providers"][name]["api_key"] = key
            configured_count += 1
            console.print(f"  [green][OK] {display_name} configured[/green]")
        else:
            console.print(f"  [dim][--] {display_name} skipped[/dim]")

    import yaml
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    console.print()
    console.print(Panel.fit(
        f"[bold green][OK] Setup complete![/bold green]\n"
        f"Config saved to: {CONFIG_FILE}\n"
        f"Providers configured: {configured_count} ({auto_detected_count} auto-detected)\n\n"
        "Run [bold]unified-router start[/bold] to start the server.",
        border_style="green",
    ))

    console.print()
    console.print("[bold]To use with OpenCode, add this to your opencode.jsonc:[/bold]")
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
    table.add_column("Category", style="dim")
    table.add_column("API Key", style="white")
    table.add_column("Status", style="green")

    registry = load_registry()

    for name in config.get("priority", []):
        pcfg = config["providers"].get(name, {})
        info = get_provider_info(name)
        display = info.get("name", name)

        section = "OpenAI"
        if any(name in registry.get("custom", {}) for _ in [1]):
            section = "Custom"

        key = pcfg.get("api_key", "")
        if key:
            key_display = key[:12] + "..." if len(key) > 12 else key
            key_cell = f"[green]{key_display}[/green]"
            status_cell = "[green][OK] Configured[/green]"
        else:
            key_cell = "[dim]none[/dim]"
            status_cell = "[dim]Not configured[/dim]"
        table.add_row(display, section, key_cell, status_cell)

    console.print(table)

    server = config.get("server", {})
    console.print(f"\n[bold]Server:[/bold] http://{server.get('host', '127.0.0.1')}:{server.get('port', 3333)}")
    console.print(f"[bold]Config:[/bold] {CONFIG_FILE}")


@app.command()
def config():
    cfg = load_config()
    registry = load_registry()

    console.print("[bold]Server Configuration:[/bold]")
    server = cfg.get("server", {})
    console.print(f"  Host: {server.get('host', '127.0.0.1')}")
    console.print(f"  Port: {server.get('port', 3333)}")
    console.print(f"  Log level: {server.get('log_level', 'info')}")

    console.print(f"\n[bold]Provider Priority Order ({len(cfg.get('priority', []))}):[/bold]")
    for i, name in enumerate(cfg.get("priority", []), 1):
        info = get_provider_info(name)
        display = info.get("name", name)
        pcfg = cfg["providers"].get(name, {})
        status = "[CONFIGURED]" if pcfg.get("api_key") else "[NOT CONFIGURED]"
        console.print(f"  {i:2d}. {display} {status}")

    console.print(f"\n[bold]Config file:[/bold] {CONFIG_FILE}")

    console.print("\n[bold]OpenCode integration snippet:[/bold]")
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
    console.print(Panel(snippet, border_style="blue"))


@app.command()
def providers():
    registry = load_registry()
    config = load_config()

    table = Table(title=f"All Providers ({len(config.get('priority', []))})")
    table.add_column("#", style="dim")
    table.add_column("Provider", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Status", style="green")
    table.add_column("Free Tier")

    for i, name in enumerate(config.get("priority", []), 1):
        info = get_provider_info(name)
        display = info.get("name", name)
        free_tier = info.get("free_tier", "")
        section = "OpenAI"
        for sname in ("openai_compatible",):
            if name in registry.get(sname, {}):
                section = "OpenAI Compatible"
                break
        if name in registry.get("custom", {}):
            section = "Custom API"
        pcfg = config["providers"].get(name, {})
        status = "[green][OK][/green]" if pcfg.get("api_key") else "[dim][--][/dim]"
        table.add_row(str(i), display, section, status, free_tier)

    console.print(table)
    console.print(f"\n[dim]Total: {len(config.get('priority', []))} providers registered[/dim]")


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
                info = get_provider_info(name)
                display = info.get("name", name)

                start = time.time()
                try:
                    models = await prov.fetch_models(client)
                    latency = f"{(time.time() - start) * 1000:.0f}ms"
                    model_count = str(len(models))
                    status_str = "[green][OK] Online[/green]"
                except Exception as e:
                    latency = "-"
                    model_count = "-"
                    status_str = f"[red][ERR] {e!s}[/red]"
                table.add_row(display, status_str, model_count, latency)

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
        script_path = Path.home() / ".local" / "bin" / "unified-router-start.cmd"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(f"""@echo off
start /B "" "{sys.executable}" -m unified_router start
""")
        console.print(f"[green]Start script created: {script_path}[/green]")
        console.print("You can add this to your startup folder or Task Scheduler.")


def main():
    app()
