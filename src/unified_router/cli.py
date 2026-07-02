from __future__ import annotations

import asyncio
import os
import sys
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns

from .config import (
    load_config,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    DEFAULT_PRIORITY,
    detect_api_key,
    detect_account_id,
    get_provider_info,
    get_provider_type,
    PROVIDER_TYPE_BADGES,
    PROVIDER_TYPE_COLORS,
    configure_opencode,
    get_router_key,
    generate_router_key,
)
from .registry import load_registry
from . import __version__

app = typer.Typer(
    name="unified-router",
    help="Unified LLM API router - route requests across 44+ free LLM providers worldwide",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def callback():
    pass


@app.command()
def version():
    console.print(f"unified-router v{__version__}")


@app.command(name="models")
def list_models(
    url: str = typer.Option("http://127.0.0.1:3333", "--url", "-u", help="Router URL"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max models to show"),
):
    import httpx
    try:
        r = httpx.get(f"{url}/v1/models", timeout=10)
        data = r.json().get("data", [])
        total = len(data)
        if limit > 0:
            data = data[:limit]
        table = Table(title=f"Available Models ({total} total, showing {len(data)})")
        table.add_column("Model ID", style="cyan")
        table.add_column("Owner", style="dim")
        for m in data:
            table.add_row(m.get("id", ""), m.get("owned_by", ""))
        console.print(table)
    except Exception as e:
        console.print(f"[red]Cannot reach router at {url}: {e}[/red]")


@app.command(name="add-key")
def add_key(
    provider: str = typer.Argument(..., help="Provider name (e.g. openrouter, groq)"),
    key: str = typer.Argument(..., help="API key value"),
):
    import yaml
    if not CONFIG_FILE.exists():
        console.print("[red]No config file found. Run 'unified-router init' first.[/red]")
        raise typer.Exit(1)
    config = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    providers = config.setdefault("providers", {})
    if provider not in providers:
        providers[provider] = {}
    providers[provider]["api_key"] = key
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    console.print(f"[green]API key set for {provider}[/green]")


@app.command(name="remove-key")
def remove_key(
    provider: str = typer.Argument(..., help="Provider name"),
):
    import yaml
    if not CONFIG_FILE.exists():
        console.print("[red]No config file found.[/red]")
        raise typer.Exit(1)
    config = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    providers = config.get("providers", {})
    if provider not in providers:
        console.print(f"[yellow]Provider '{provider}' not found in config.[/yellow]")
        raise typer.Exit(1)
    providers[provider].pop("api_key", None)
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    console.print(f"[green]API key removed for {provider}[/green]")


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
def stop():
    pid_file = CONFIG_DIR / "router.pid"
    if not pid_file.exists():
        console.print("[yellow]Router is not running (no PID file found).[/yellow]")
        return
    
    try:
        pid = int(pid_file.read_text().strip())
        import os
        import signal
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to Unified Router (PID: {pid})[/green]")
    except ProcessLookupError:
        console.print("[yellow]Process not found. Cleaning up PID file.[/yellow]")
        pid_file.unlink()
    except Exception as e:
        console.print(f"[red]Error stopping router: {e}[/red]")


def _open_browser(url: str):
    try:
        webbrowser.open(url)
        console.print(f"  [dim]Opened: {url}[/dim]")
    except Exception:
        console.print(f"  [dim]Signup URL: {url}[/dim]")


def _print_provider_group(title: str, providers: list, style: str, show_type: bool = True):
    if not providers:
        return
    console.print(f"\n[bold {style}]  {title}[/bold {style}]")
    for name, reg in providers:
        badge = PROVIDER_TYPE_BADGES.get(get_provider_type(name), "")
        display = reg.get("name", name)
        free_tier = reg.get("free_tier", "")
        signup = reg.get("signup_url", "")
        label = f"    {badge} {display}"
        if free_tier:
            label += f"  [dim]{free_tier}[/dim]"
        console.print(label)


def _group_providers(registry: dict) -> dict[str, list]:
    groups: dict[str, list] = {"free": [], "phone": [], "credits": [], "paid": []}

    for section in ("openai_compatible", "custom"):
        for name, reg in registry.get(section, {}).items():
            ptype = reg.get("type", "free")
            if ptype not in groups:
                groups[ptype] = []
            groups[ptype].append((name, reg))

    return groups


def _run_health_check():
    async def _check():
        config = load_config()
        from .registry import build_providers
        providers = build_providers(config)

        if not providers:
            console.print("[red]No providers configured to test.[/red]")
            return

        import time
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            table = Table(title="Provider Health Check")
            table.add_column("Provider", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Models", style="white")
            table.add_column("Latency", style="white")

            for name, prov in providers.items():
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
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    auto: bool = typer.Option(False, "--auto", "-a", help="Only use env-detected keys, skip interactive prompts"),
    guide: bool = typer.Option(False, "--guide", "-g", help="Walk through signing up for top providers"),
):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists() and not force:
        console.print("[yellow]Config already exists at ~/.config/unified-router/config.yml[/yellow]")
        console.print("Run with --force to overwrite")
        return

    registry = load_registry()
    config = DEFAULT_CONFIG.copy()
    config["priority"] = list(DEFAULT_CONFIG["priority"])
    config["providers"] = {k: dict(v) for k, v in DEFAULT_CONFIG["providers"].items()}

    # --- Phase 1: Pre-detect all environment keys ---
    auto_detected_count = 0
    configured_count = 0

    for name, pcfg in config["providers"].items():
        detected = detect_api_key(pcfg)
        if detected:
            config["providers"][name]["api_key"] = detected
            auto_detected_count += 1
            configured_count += 1

    # --- Phase 2: Strategy Selection (skip if --auto or forced) ---
    if guide:
        strategy = "guide"
    elif auto:
        strategy = "auto"
    elif sys.stdin.isatty():
        console.print(Panel.fit(
            "[bold cyan]Unified Router - Setup Wizard[/bold cyan]\n"
            f"[dim]Welcome! This wizard connects your LLM providers so you can route requests across them.\n"
            f"I auto-detected [bold]{auto_detected_count}[/bold] API keys from your environment.[/dim]\n\n"
            "How would you like to proceed?",
            border_style="cyan",
        ))
        console.print()
        console.print("  [bold]1)[/bold] Web Dashboard [dim](set up API keys visually at localhost:3333/settings)[/dim]")
        console.print("  [bold]2)[/bold] CLI Wizard [dim](type or paste each key into the terminal)[/dim]")
        console.print(f"  [bold]3)[/bold] Auto-Detect Only [dim](use only the {auto_detected_count} keys found in env vars)[/dim]")
        console.print()
        choice = input("  Choice [1]: ").strip() or "1"
        if choice == "1":
            strategy = "web"
        elif choice == "3":
            strategy = "auto"
        else:
            strategy = "cli"
    else:
        strategy = "cli"

    # --- Phase 3: Interactive CLI configuration (if chosen) ---
    if strategy == "cli":
        groups = _group_providers(registry)
        group_titles = {
            "free": "[Easy] Always Free - No phone, no credit card required",
            "phone": "[Phone] Phone Verify Required",
            "credits": "[Credits] Free Trials & Credits",
            "paid": "[Paid] Paid Services (no free tier)",
        }
        group_styles = {
            "free": "green",
            "phone": "yellow",
            "credits": "blue",
            "paid": "dim",
        }

        if guide:
            console.print("\n[bold yellow]Guide Mode[/bold yellow] - Let's walk through getting keys for the top providers:")
            console.print("  We'll open signup pages so you can create accounts and generate API keys.")
            input("  Press Enter to start...")

        for group_key in ("free", "phone", "credits", "paid"):
            group = groups.get(group_key, [])
            if not group:
                continue
            title = group_titles.get(group_key, group_key)
            style = group_styles.get(group_key, "white")
            console.print(f"\n[bold {style}]  {title}[/bold {style}]")

            for name, reg in group:
                display_name = reg.get("name", name)
                signup_url = reg.get("signup_url", "")
                badge = PROVIDER_TYPE_BADGES.get(group_key, "")
                pcfg = config["providers"].get(name, {})
                needs_account = bool(reg.get("env_account_id"))
                current_key = pcfg.get("api_key", "") or ""

                if current_key:
                    configured_count += 1
                    continue

                if guide:
                    console.print(f"\n  [bold]{display_name}[/bold] {badge}")
                    free_tier = reg.get("free_tier", "")
                    if free_tier:
                        console.print(f"  [dim]Free tier: {free_tier}[/dim]")
                    console.print(f"  Signup: [blue]{signup_url}[/blue]")
                    answer = input("  Open signup page? [Y/n]: ").strip().lower()
                    if answer == "y" or answer == "":
                        _open_browser(signup_url)
                    console.print(f"  [dim]After signing up, run 'unified-router init' again to add your key.[/dim]")
                    input("  Press Enter to continue...")
                else:
                    if needs_account:
                        console.print(f"\n  [bold]{display_name}[/bold] {badge}")
                        console.print(f"  Get API token at: [blue]{signup_url}[/blue]")
                        console.print(f"  Also need your Account ID from the provider dashboard.")
                        answer = input("  Open signup page? [Y/n/o]: ").strip().lower()
                        if answer == "o" or answer == "y" or answer == "":
                            _open_browser(signup_url)
                        current_acct_val = detect_account_id(pcfg) or ""
                        acct_prompt = f"  Account ID [{current_acct_val}]: " if current_acct_val else "  Account ID (required, press Enter to skip): "
                        acct = input(acct_prompt).strip()
                        if not acct and current_acct_val:
                            acct = current_acct_val
                        if acct:
                            config["providers"][name]["account_id"] = acct
                            console.print(f"  [dim]Account ID set[/dim]")
                        else:
                            console.print(f"  [dim][--] {display_name} skipped (no account ID)[/dim]")
                            continue
                        key = input(f"  API key (or press Enter to skip): ").strip()
                        if key:
                            config["providers"][name]["api_key"] = key
                            configured_count += 1
                            console.print(f"  [green]  [OK] {display_name} configured[/green]")
                        else:
                            console.print(f"  [dim]  [--] {display_name} skipped[/dim]")
                    else:
                        if signup_url:
                            console.print(f"  Get key at: [blue]{signup_url}[/blue]")
                        key = input(f"  {badge} {display_name} - API key (or press Enter to skip, 'o' to open signup): ").strip()
                        if key.lower() == "o":
                            _open_browser(signup_url)
                            key = input(f"  {badge} {display_name} - API key (or press Enter to skip): ").strip()
                        if key:
                            config["providers"][name]["api_key"] = key
                            configured_count += 1
                            console.print(f"  [green]  [OK] {display_name} configured[/green]")
                        else:
                            console.print(f"  [dim]  [--] {display_name} skipped[/dim]")

    else:
        # For web or auto strategy, configured_count already reflects auto-detected
        pass

    # --- Phase 4: Write config ---
    import yaml
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    # --- Phase 4b: Generate router API key ---
    router_key = get_router_key()
    server_cfg = config.get("server", {})
    base_url = f"http://{server_cfg.get('host', '127.0.0.1')}:{server_cfg.get('port', 3333)}/v1"

    # --- Phase 5: Summary & Next Steps ---
    console.print()
    console.print(Panel.fit(
        f"[bold green][OK] Setup complete![/bold green]\n"
        f"Config saved to: {CONFIG_FILE}\n"
        f"Providers configured: {configured_count} (via env vars: {auto_detected_count})\n"
        f"Providers available via dashboard: {len(config['providers'])}\n\n"
        f"[bold]Router API Key:[/bold] [cyan]{router_key}[/cyan]\n"
        f"[bold]Base URL:[/bold] [cyan]{base_url}[/cyan]\n\n"
        f"[bold]Next Steps:[/bold]\n"
        + (f"  - Open [bold]http://{server_cfg.get('host', '127.0.0.1')}:{server_cfg.get('port', 3333)}/settings[/bold] to add more API keys\n" if strategy != "cli" else "  - Start the router: [bold]unified-router start[/bold]\n")
        + "  - Start the router: [bold]unified-router start[/bold]\n"
        + "  - In OpenCode desktop, run [bold]/connect[/bold] -> [bold]Other[/bold] (Custom provider)\n"
        f"    - Provider ID: [cyan]unified-router[/cyan]\n"
        f"    - Display name: [cyan]Unified Router[/cyan]\n"
        f"    - Base URL: [cyan]{base_url}[/cyan]\n"
        f"    - API key: [cyan]{router_key}[/cyan]\n"
        f"    - Models (optional): leave empty to auto-discover\n"
        f"    - Headers: leave empty",
        border_style="green",
    ))

    # --- Phase 6: OpenCode Configuration ---
    console.print()
    if sys.stdin.isatty():
        setup_opencode = input("  Would you like to automatically configure OpenCode? [Y/n]: ").strip().lower()
    else:
        setup_opencode = "y"
    if setup_opencode == "y" or setup_opencode == "":
        success, msg = configure_opencode(router_key=router_key)
        if success:
            console.print("[green]  [OK] OpenCode configured successfully![/green]")
            console.print(f"  [dim]Router API key written to opencode.jsonc:[/dim]  [cyan]{router_key}[/cyan]")
        else:
            console.print(f"[yellow]  [ERR] Could not auto-configure OpenCode: {msg}[/yellow]")
            console.print("  [dim]You can manually add the provider to your opencode.jsonc file.[/dim]")
            console.print("  [dim]Run 'unified-router config' to see the snippet.[/dim]")

    if configured_count > 0 and sys.stdin.isatty() and strategy == "cli":
        console.print()
        test_choice = input("  Test your configured providers now? [Y/n]: ").strip().lower()
        if test_choice == "y" or test_choice == "":
            _run_health_check()



@app.command()
def status():
    config = load_config()
    registry = load_registry()

    table = Table(title="Provider Status")
    table.add_column("Provider", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Key", style="white")
    table.add_column("Status", style="green")

    for name in config.get("priority", []):
        pcfg = config["providers"].get(name, {})
        info = get_provider_info(name)
        display = info.get("name", name)
        ptype = get_provider_type(name)
        badge = PROVIDER_TYPE_BADGES.get(ptype, "")
        badge_color = PROVIDER_TYPE_COLORS.get(ptype, "white")

        key = pcfg.get("api_key", "")
        if key:
            key_display = key[:12] + "..." if len(key) > 12 else key
            key_cell = f"[green]{key_display}[/green]"
            status_cell = "[green][OK] Configured[/green]"
        else:
            key_cell = "[dim]none[/dim]"
            status_cell = "[dim]Not configured[/dim]"

        table.add_row(f"{badge} {display}", f"[{badge_color}]{ptype}[/{badge_color}]", key_cell, status_cell)

    console.print(table)

    server = config.get("server", {})
    console.print(f"\n[bold]Server:[/bold] http://{server.get('host', '127.0.0.1')}:{server.get('port', 3333)}")
    console.print(f"[bold]Config:[/bold] {CONFIG_FILE}")
    total = len(config.get("priority", []))
    configured = sum(1 for p in config.get("providers", {}).values() if p.get("api_key"))
    console.print(f"[bold]{configured}/{total}[/bold] providers configured")


@app.command()
def config():
    cfg = load_config()

    console.print("[bold]Server Configuration:[/bold]")
    server = cfg.get("server", {})
    console.print(f"  Host: {server.get('host', '127.0.0.1')}")
    console.print(f"  Port: {server.get('port', 3333)}")
    console.print(f"  Log level: {server.get('log_level', 'info')}")

    console.print(f"\n[bold]Provider Priority ({len(cfg.get('priority', []))} total):[/bold]")
    for i, name in enumerate(cfg.get("priority", []), 1):
        info = get_provider_info(name)
        display = info.get("name", name)
        ptype = get_provider_type(name)
        badge = PROVIDER_TYPE_BADGES.get(ptype, "")
        pcfg = cfg["providers"].get(name, {})
        status = "[CONFIGURED]" if pcfg.get("api_key") else ""
        console.print(f"  {i:2d}. {badge} {display} {status}")

    console.print(f"\n[bold]Config file:[/bold] {CONFIG_FILE}")

    console.print("\n[bold]OpenCode integration snippet:[/bold]")
    router_key = get_router_key()
    server = cfg.get("server", {})
    base_url = f"http://{server.get('host', '127.0.0.1')}:{server.get('port', 3333)}/v1"
    snippet = f'''{{
  "$schema": "https://opencode.ai/config.json",
  "provider": {{
    "unified-router": {{
      "npm": "@ai-sdk/openai-compatible",
      "name": "Unified Router",
      "options": {{
        "baseURL": "{base_url}",
        "apiKey": "{router_key}"
      }}
    }}
  }}
}}'''
    console.print(Panel(snippet, border_style="blue"))


@app.command()
def providers():
    registry = load_registry()
    groups = _group_providers(registry)
    group_titles = {
        "free": "Always Free (no phone/card)",
        "phone": "Phone Verify Required",
        "credits": "Free Trials & Credits",
        "paid": "Paid Services (no free tier)",
    }
    group_styles = {
        "free": "green",
        "phone": "yellow",
        "credits": "blue",
        "paid": "dim",
    }

    total = sum(len(g) for g in groups.values())
    console.print(f"[bold]All Providers ({total})[/bold]\n")

    for group_key in ("free", "phone", "credits", "paid"):
        group = groups.get(group_key, [])
        if not group:
            continue
        title = group_titles.get(group_key, group_key)
        style = group_styles.get(group_key, "white")
        console.print(f"[bold {style}]  {title}[/bold {style}]")

        table = Table(box=None, padding=(0, 2), show_header=False)
        table.add_column("", style="dim", width=4)
        table.add_column("", style="cyan")
        table.add_column("", style="dim", width=16)
        table.add_column("", style="white")

        for name, reg in group:
            badge = PROVIDER_TYPE_BADGES.get(group_key, "")
            display = reg.get("name", name)
            free_tier = reg.get("free_tier", "")
            signup = reg.get("signup_url", "")
            table.add_row("", f"{badge} {display}", f"[dim]{free_tier[:30]}[/dim]" if free_tier else "", f"[dim]{signup}[/dim]")

        console.print(table)

    console.print(f"\n[bold]Suggested priority order:[/bold]")
    for i, name in enumerate(DEFAULT_PRIORITY, 1):
        info = get_provider_info(name)
        badge = PROVIDER_TYPE_BADGES.get(get_provider_type(name), "")
        display = info.get("name", name)
        console.print(f"  {i:2d}. {badge} {display}")


@app.command()
def health():
    _run_health_check()


@app.command()
def dashboard(
    url: str = typer.Option("http://127.0.0.1:3333", "--url", "-u", help="Router URL"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Refresh interval seconds"),
    once: bool = typer.Option(False, "--once", help="Print once and exit"),
):
    import httpx
    import time

    def _render(data: dict):
        table = Table(title="Unified Router - Live Dashboard")
        table.add_column("Provider", style="cyan")
        table.add_column("Reqs", style="white")
        table.add_column("Errors", style="red")
        table.add_column("Tokens", style="green")
        table.add_column("Latency", style="white")
        table.add_column("Status", style="yellow")

        provs = data.get("providers", {})
        total_reqs = 0
        total_tokens = 0
        total_errors = 0
        for name, s in provs.items():
            reqs = s.get("requests", 0)
            errs = s.get("errors", 0)
            toks = s.get("tokens", 0)
            lat = s.get("latency_ema_ms", 0)
            rl = s.get("rate_limited", False)
            status = "[red]RATE LIMITED[/red]" if rl else "[green]OK[/green]"
            table.add_row(name, str(reqs), str(errs), str(toks), f"{lat}ms", status)
            total_reqs += reqs
            total_tokens += toks
            total_errors += errs

        console.print(table)
        console.print(f"[bold]Totals:[/bold] {total_reqs} reqs | {total_tokens} tokens | {total_errors} errors")

        cache_info = data.get("cache", {})
        if cache_info:
            console.print(f"[bold]Cache:[/bold] {cache_info.get('hits',0)} hits / {cache_info.get('misses',0)} misses | {cache_info.get('size',0)} entries")

    if once:
        try:
            r = httpx.get(f"{url}/v1/stats", timeout=5)
            _render(r.json())
        except Exception as e:
            console.print(f"[red]Cannot reach router at {url}: {e}[/red]")
        return

    console.print(f"[dim]Live dashboard — polling {url} every {interval}s. Ctrl+C to exit.[/dim]")
    try:
        with httpx.Client(timeout=5) as c:
            while True:
                console.clear()
                try:
                    r = c.get(f"{url}/v1/stats")
                    _render(r.json())
                except Exception as e:
                    console.print(f"[red]Cannot reach router at {url}: {e}[/red]")
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


@app.command()
def guide():
    console.print(Panel.fit(
        "[bold cyan]Unified Router - Getting Started Guide[/bold cyan]\n"
        "We'll help you sign up for the top free providers and get your API keys.\n"
        "[dim]Press Enter to continue through each step.[/dim]",
        border_style="cyan",
    ))

    registry = load_registry()

    guide_providers = [
        ("openrouter", "OpenRouter", "https://openrouter.ai/settings/keys",
         "Has 20+ free models. No phone or credit card needed."),
        ("groq", "Groq", "https://console.groq.com/keys",
         "Fastest inference. Generous free tier. No phone or card needed."),
        ("gemini", "Google Gemini", "https://aistudio.google.com/app/apikey",
         "Google's models. Free tier: 20-1500 req/day per model."),
        ("opencode_zen", "OpenCode Zen", "https://opencode.ai/auth",
         "OpenCode's tested/verified models. Free models available."),
        ("nvidia", "NVIDIA NIM", "https://build.nvidia.com",
         "40 RPM no daily cap. Requires phone verification."),
    ]

    for key, display, url, desc in guide_providers:
        info = get_provider_info(key)
        badge = PROVIDER_TYPE_BADGES.get(get_provider_type(key), "")
        console.print(f"\n[bold cyan]{badge} {display}[/bold cyan]")
        console.print(f"  {desc}")
        console.print(f"  Signup URL: [blue]{url}[/blue]")
        answer = input("  Open signup page? [Y/n]: ").strip().lower()
        if answer == "y" or answer == "":
            _open_browser(url)
        input("  Press Enter for next provider...")

    console.print()
    console.print(Panel.fit(
        "[bold green]Once you have your API keys, run:[/bold green]\n"
        "  unified-router init\n\n"
        "The wizard will auto-detect any keys you've set as environment variables\n"
        "and prompt you for the rest.",
        border_style="green",
    ))


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
