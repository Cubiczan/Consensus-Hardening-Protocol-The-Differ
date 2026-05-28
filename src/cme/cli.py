"""CLI for Consensus Commons — Spacebase1 multi-agent decision rooms.

Usage:
    cme spacebase-demo --mock --topic "Should Spacebase1 fund a public agent council?"
    cme spacebase-demo --mock --root-intent abc123 --out-md demo_output.md
    cme spacebase-demo --live --station-token $TOKEN --topic "Capital allocation Q3"
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from cme.spacebase.models import Intent, LockState
from cme.spacebase.client import MockSpacebaseClient, HttpSpacebaseClient
from cme.spacebase.adapter import SpacebaseAdapter
from cme.spacebase.routing import IntentRouter
from cme.spacebase.council import CouncilRunner

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.version_option(package_name="consensus-commons")
def main() -> None:
    """Consensus Commons — Spacebase1 multi-agent decision rooms."""
    _setup_logging()


# ---------------------------------------------------------------------------
# spacebase-demo
# ---------------------------------------------------------------------------


@main.command()
@click.option("--mock", is_flag=True, default=False, help="Use mock Spacebase client (offline mode).")
@click.option("--live", is_flag=True, default=False, help="Use live Spacebase1 HTTP client.")
@click.option("--station-token", envvar="SPACEBASE_STATION_TOKEN", default=None, help="Station token for live mode.")
@click.option("--root-intent", default=None, help="Use an existing intent ID as the root decision room.")
@click.option("--topic", default=None, help="Topic for the council deliberation.")
@click.option("--out-md", default=None, type=click.Path(), help="Write council report to markdown file.")
@click.option("--verbose", is_flag=True, default=False, help="Enable verbose logging.")
@click.option("--max-agents", default=4, type=int, help="Maximum number of agents to spawn.")
def spacebase_demo(
    mock: bool,
    live: bool,
    station_token: Optional[str],
    root_intent: Optional[str],
    topic: Optional[str],
    out_md: Optional[str],
    verbose: bool,
    max_agents: int,
) -> None:
    """Run a Consensus Commons council deliberation.

    In mock mode, creates a deterministic demo with simulated agents.
    In live mode, connects to Spacebase1 and runs a real council.

    Example:
        cme spacebase-demo --mock --topic "Should we fund public AI governance?"
        cme spacebase-demo --live --station-token $TOKEN --topic "Q3 capital allocation"
    """
    _setup_logging(verbose)
    logger = logging.getLogger(__name__)

    if not mock and not live:
        console.print("[yellow]No mode specified. Defaulting to --mock.[/yellow]")
        mock = True

    if live and not station_token:
        console.print("[red]Error: --station-token required for live mode.[/red]")
        console.print("Set SPACEBASE_STATION_TOKEN env var or pass --station-token.")
        sys.exit(1)

    default_topic = "Should Spacebase1 fund a public agent council for grant allocation?"
    topic = topic or default_topic

    console.print(Panel(
        f"[bold]Consensus Commons[/bold] — Multi-Agent Decision Council\n\n"
        f"Mode: {'MOCK (offline)' if mock else 'LIVE (Spacebase1)'}\n"
        f"Topic: {topic}\n"
        f"Max agents: {max_agents}",
        title="Council Session",
        border_style="blue",
    ))

    asyncio.run(_run_demo(
        mock=mock,
        live=live,
        station_token=station_token,
        root_intent_id=root_intent,
        topic=topic,
        out_md=out_md,
        max_agents=max_agents,
    ))


async def _run_demo(
    mock: bool,
    live: bool,
    station_token: str | None,
    root_intent_id: str | None,
    topic: str,
    out_md: str | None,
    max_agents: int,
) -> None:
    """Execute the council demo."""
    logger = logging.getLogger(__name__)

    # Create client
    if mock:
        client = MockSpacebaseClient(commons_space="demo-commons")
    else:
        client = HttpSpacebaseClient(
            station_token=station_token or "",
            agent_name="consensus-commons",
        )
        await client.connect()

    try:
        # Create or use root intent
        if root_intent_id:
            intent = await client.enter(root_intent_id)
            if intent is None:
                console.print(f"[red]Error: Intent {root_intent_id} not found.[/red]")
                return
        else:
            intent = await client.post(
                content=topic,
                payload={"kind": "council-root", "event": "consensus-commons-demo"},
            )
            root_intent_id = intent.intent_id

        console.print(f"\n[green]Root intent created:[/green] {intent.intent_id}")
        console.print(f"[dim]Content: {intent.content[:100]}...[/dim]")

        # Create adapter
        adapter = SpacebaseAdapter(client=client)

        # Route the intent
        router = IntentRouter()
        route = router.classify(intent)

        console.print(f"\n[blue]Route:[/blue] {route.role}")
        console.print(f"[dim]Agents: {', '.join(route.agents)}[/dim]")
        console.print(f"[dim]Confidence: {route.confidence:.0%}[/dim]")
        console.print(f"[dim]Reason: {route.reason}[/dim]")

        if not route.is_supported:
            console.print(f"\n[red]Intent not supported: {route.reason}[/red]")
            return

        # Run the council
        console.print("\n[bold cyan]Starting council deliberation...[/bold cyan]")

        with console.status("[bold green]Running multi-agent council...", spinner="dots"):
            report = await adapter.run_council(
                intent=intent,
                topic=topic,
                max_agents=max_agents,
            )

        # Display results
        _display_report(report)

        # Save markdown if requested
        if out_md:
            md_content = report.to_markdown()
            Path(out_md).write_text(md_content, encoding="utf-8")
            console.print(f"\n[green]Report saved to:[/green] {out_md}")

        # Display the post tree
        tree = await client.get_post_tree(root_intent_id)
        if tree:
            console.print("\n[bold]Decision Room Tree (Nested Intent Space):[/bold]")
            _display_tree(tree)

        # Summary
        console.print(Panel(
            f"[bold green]Council Complete[/bold green]\n\n"
            f"Posts created: {len(report.posts)}\n"
            f"Final state: {report.final_state.value}\n"
            f"Duration: {report.duration:.2f}s\n"
            f"Trace ID: {report.trace_id}",
            title="Result",
            border_style="green",
        ))

    finally:
        if hasattr(client, "close"):
            await client.close()


def _display_report(report: Any) -> None:
    """Display the council report in a rich table."""
    table = Table(title="Agent Contributions", show_lines=True)
    table.add_column("Agent", style="cyan")
    table.add_column("Post ID", style="dim")
    table.add_column("Title")
    table.add_column("Confidence")
    table.add_column("Lock State")
    table.add_column("Trace ID", style="dim")

    for post in report.posts:
        conf = f"{post.confidence:.0%}" if post.confidence else "N/A"
        table.add_row(
            post.agent,
            post.post_id,
            post.title,
            conf,
            post.lock_state.value,
            post.trace_id,
        )

    console.print(table)


def _display_tree(tree: Any, depth: int = 0) -> None:
    """Display a PostTree as a rich Tree widget."""
    if depth == 0:
        rich_tree = Tree(f"[bold]ROOT[/bold] {tree.post.title}")
    else:
        return

    def _add_node(parent: Tree, node: Any) -> None:
        p = node.post
        if p.agent:
            label = f"[cyan][{p.agent}][/cyan] {p.title}"
        else:
            label = f"{p.title}"
        if p.lock_state:
            label += f" [{p.lock_state.value}]"
        branch = parent.add(label)
        for child in node.children:
            _add_node(branch, child)

    for child in tree.children:
        _add_node(rich_tree, child)

    console.print(rich_tree)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@main.command()
@click.option("--mock", is_flag=True, default=True, help="Use mock client.")
@click.option("--space-id", default="commons", help="Space ID to scan.")
@click.option("--json", "output_json", is_flag=True, default=False, help="Output as JSON.")
def scan(mock: bool, space_id: str, output_json: bool) -> None:
    """Scan a Spacebase1 space for candidate intents."""
    _setup_logging()
    asyncio.run(_scan_space(mock, space_id, output_json))


async def _scan_space(mock: bool, space_id: str, output_json: bool) -> None:
    client = MockSpacebaseClient() if mock else HttpSpacebaseClient(station_token="")
    if not mock:
        await client.connect()

    adapter = SpacebaseAdapter(client=client)
    results = await adapter.scan_intents(space_id)

    if output_json:
        data = []
        for r in results:
            data.append({
                "intent_id": r["intent"].intent_id,
                "content": r["intent"].content[:100],
                "role": r["route"].role,
                "supported": r["route"].is_supported,
                "is_new": r["is_new"],
            })
        console.print_json(json.dumps(data))
    else:
        table = Table(title=f"Intents in '{space_id}'")
        table.add_column("Intent ID", style="dim")
        table.add_column("Content")
        table.add_column("Route")
        table.add_column("Supported")
        table.add_column("New")
        for r in results:
            table.add_row(
                r["intent"].intent_id,
                r["intent"].content[:60],
                r["route"].role,
                "[green]Yes[/green]" if r["route"].is_supported else "[red]No[/red]",
                "[yellow]Yes[/yellow]" if r["is_new"] else "[dim]No[/dim]",
            )
        console.print(table)

    if hasattr(client, "close"):
        await client.close()


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@main.command()
def info() -> None:
    """Show Consensus Commons project information."""
    console.print(Panel(
        "[bold]Consensus Commons[/bold] v0.1.0\n\n"
        "A Spacebase1 adapter that turns public intents into visible\n"
        "multi-agent decision rooms with consensus hardening.\n\n"
        "[cyan]Architecture:[/cyan]\n"
        "  Spacebase root intent → decision problem\n"
        "  Each TurnResult → child intent (agent post)\n"
        "  Expansion/compression trace → post body\n"
        "  Final Workflow → summary child\n"
        "  CHP/adversary output → validation child\n\n"
        "[cyan]Commands:[/cyan]\n"
        "  cme spacebase-demo --mock --topic '...'\n"
        "  cme scan --space-id commons\n"
        "  cme info\n\n"
        "[cyan]Protocol:[/cyan] ITP (Intent Transport Protocol)",
        title="Consensus Commons",
        border_style="blue",
    ))


if __name__ == "__main__":
    main()
