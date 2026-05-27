#!/usr/bin/env python3
"""Natural language to SPARQL + SQL query engine for the university dataset."""

import sys
import os
import concurrent.futures

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.columns import Columns
from rich import box

import nl_translator
import sparql_executor
import sql_executor
import datasets

console = Console()


def _df_to_rich_table(title: str, df: pd.DataFrame, style: str) -> Table:
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style=style,
        header_style=f"bold {style}",
        show_lines=True,
    )
    for col in df.columns:
        table.add_column(str(col), overflow="fold")
    for _, row in df.iterrows():
        table.add_row(*[str(v) if v is not None else "" for v in row])
    return table


def run(question: str, dataset: str = "university") -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Translate question to SPARQL (+ SQL where the dataset supports it), execute,
    and display results. Returns (sparql_df, sql_df); sql_df is empty for
    SPARQL-only datasets.
    """
    cfg = datasets.get(dataset)
    endpoint = cfg["sparql_endpoint"]
    do_sql = "sql" in cfg["languages"]

    console.print()
    console.rule(f"[bold cyan]Question[/bold cyan] [dim]· {cfg['label']}[/dim]")
    console.print(f"[italic]{question}[/italic]\n")

    # ── Generate queries ──────────────────────────────────────────────────
    console.print("[bold]Generating queries with Claude…[/bold]")
    try:
        sparql, sql = nl_translator.translate(question, dataset)
    except RuntimeError as exc:
        console.print(f"[bold red]Translation error:[/bold red] {exc}")
        sys.exit(1)

    console.print(
        Panel(
            Syntax(sparql, "sparql", theme="monokai", word_wrap=True),
            title="[bold green]Generated SPARQL[/bold green]",
            border_style="green",
        )
    )
    if do_sql:
        console.print(
            Panel(
                Syntax(sql, "sql", theme="monokai", word_wrap=True),
                title="[bold blue]Generated SQL[/bold blue]",
                border_style="blue",
            )
        )

    # ── Execute (SPARQL always; SQL when supported) ───────────────────────
    console.print("\n[bold]Executing queries…[/bold]")
    sparql_result: pd.DataFrame | Exception
    sql_result: pd.DataFrame | Exception | None = None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        sparql_future = pool.submit(sparql_executor.execute, sparql, endpoint)
        sql_future = pool.submit(sql_executor.execute, sql) if do_sql else None
        try:
            sparql_result = sparql_future.result()
        except Exception as exc:  # noqa: BLE001
            sparql_result = exc
        if sql_future is not None:
            try:
                sql_result = sql_future.result()
            except Exception as exc:  # noqa: BLE001
                sql_result = exc

    # ── Display results ───────────────────────────────────────────────────
    console.print()
    console.rule("[bold]Results[/bold]")
    console.print()

    renderables = []

    if isinstance(sparql_result, Exception):
        renderables.append(
            Panel(
                f"[bold red]{sparql_result}[/bold red]",
                title="[bold green]SPARQL Results — ERROR[/bold green]",
                border_style="green",
            )
        )
        sparql_df = pd.DataFrame()
    else:
        sparql_df = sparql_result
        if not sparql_df.empty:
            renderables.append(_df_to_rich_table("SPARQL Results", sparql_df, "green"))
        else:
            renderables.append(
                Panel("[dim]No results returned.[/dim]", title="SPARQL Results", border_style="green")
            )

    sql_df = pd.DataFrame()
    if do_sql:
        if isinstance(sql_result, Exception):
            renderables.append(
                Panel(
                    f"[bold red]{sql_result}[/bold red]",
                    title="[bold blue]SQL Results — ERROR[/bold blue]",
                    border_style="blue",
                )
            )
        else:
            sql_df = sql_result
            if not sql_df.empty:
                renderables.append(_df_to_rich_table("SQL Results", sql_df, "blue"))
            else:
                renderables.append(
                    Panel("[dim]No results returned.[/dim]", title="SQL Results", border_style="blue")
                )

    if do_sql and console.width >= 120:
        console.print(Columns(renderables, equal=True, expand=True))
    else:
        for r in renderables:
            console.print(r)
            console.print()

    return sparql_df, sql_df


def main() -> None:
    args = sys.argv[1:]
    dataset = datasets.DEFAULT_DATASET
    rest = []
    i = 0
    while i < len(args):
        if args[i] in ("--dataset", "-d") and i + 1 < len(args):
            dataset = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1

    if not rest:
        console.print('[bold red]Usage:[/bold red] python src/nl_query.py [--dataset university|hr] "<your question>"')
        console.print()
        console.print("Examples:")
        console.print('  python src/nl_query.py "List all students"')
        console.print('  python src/nl_query.py --dataset hr "Which employees are software engineers across all subsidiaries?"')
        console.print('  python src/nl_query.py --dataset hr "Which role mappings need review?"')
        sys.exit(1)

    if dataset not in datasets.DATASETS:
        console.print(f"[bold red]Unknown dataset '{dataset}'.[/bold red] Choices: {', '.join(datasets.DATASETS)}")
        sys.exit(1)

    question = " ".join(rest)
    sparql_df, sql_df = run(question, dataset)

    console.print("\n[dim]DataFrames available as sparql_df and sql_df[/dim]")
    console.print(f"[dim]sparql_df: {sparql_df.shape[0]} rows × {sparql_df.shape[1]} cols[/dim]")
    if "sql" in datasets.get(dataset)["languages"]:
        console.print(f"[dim]  sql_df: {sql_df.shape[0]} rows × {sql_df.shape[1]} cols[/dim]")


if __name__ == "__main__":
    main()
