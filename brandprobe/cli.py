"""Thin command handlers; all audit behavior lives in the shared core."""

import argparse
from pathlib import Path
import httpx
from brandprobe.config import api_key, load_config
from brandprobe.engine import execute
from brandprobe.llm import catalog
from brandprobe.planning import make_plan
from brandprobe.report import html_report, report_data


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Measure how models recognize and mention a brand, with inspectable evidence."
    )
    p.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project directory for secrets and history (default: current directory).",
    )
    sub = p.add_subparsers(dest="command", required=True)
    for name, description in [
        ("demo", "Run synthetic fixtures without network or paid calls."),
        ("plan", "Preview current prices and the exact live audit scope."),
        ("run", "Review a price preview, then confirm a paid audit interactively."),
    ]:
        cmd = sub.add_parser(name, help=description, description=description)
        cmd.add_argument(
            "--config",
            type=Path,
            default=Path("examples/sots.toml"),
            help="Audit TOML path relative to root (default: examples/sots.toml).",
        )
        cmd.add_argument(
            "--model",
            action="append",
            help="Exact OpenRouter model ID; repeat to select several models.",
        )
    sub.add_parser(
        "models",
        help="List current eligible OpenRouter model IDs and prices.",
        description="Fetch the public model catalog; no paid inference.",
    )
    serve = sub.add_parser(
        "serve",
        help="Start the local browser interface on loopback.",
        description="Start the local BrandProbe browser interface.",
    )
    serve.add_argument(
        "--port", type=int, default=8765, help="Loopback port (default: 8765)."
    )
    return p


async def run_command(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    async with httpx.AsyncClient(timeout=30) as client:
        if args.command == "models":
            for model in await catalog(client):
                print(
                    f"{model.id}  input ${model.input_per_token * 1000000}/M, output ${model.output_per_token * 1000000}/M"
                )
            return
        config = load_config(root / args.config)
        if args.model:
            config = type(config).model_validate(
                {**config.model_dump(), "models": args.model}
            )
        plan = await make_plan(config, args.command == "demo", client)
    print(
        f"{plan.mode}: {plan.requests} responses + {plan.evaluation_requests} scoring requests; estimated ${plan.estimated_usd:.4f}; conservative reservation ${plan.reserved_usd:.4f}; budget ${config.budget_usd}"
    )
    if args.command == "plan":
        print(plan.model_dump_json(indent=2))
        return
    if args.command == "run":
        if input("Type RUN to approve this paid audit: ").strip() != "RUN":
            print("Cancelled; no model requests sent.")
            return
    audit = await execute(root, plan, api_key(root), approved=args.command == "run")
    folder = root / ".brandprobe" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{audit.id}.html").write_text(html_report(audit))
    (folder / f"{audit.id}.json").write_text(
        __import__("json").dumps(report_data(audit), indent=2)
    )
    print(
        f"{audit.status}: {len(audit.observations)} responses saved. Report: {folder / (audit.id + '.html')}"
    )
