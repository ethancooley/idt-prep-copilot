"""Generate an IDT brief for one participant.

    python -m idt_copilot.agent.run --participant "Mariana Arriaga"
    python -m idt_copilot.agent.run --participant 08e17e4e-b18f-32c9-fbf5-996e180b5ca3

Needs ANTHROPIC_API_KEY (in the environment or .env) and the database from docker compose.
Writes briefs/<participant id>.json and .md.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from idt_copilot.agent.chart_client import InProcessChartClient, MCPChartClient
from idt_copilot.agent.graph import AgentConfig, render_markdown, run_agent
from idt_copilot.agent.llm import LLM
from idt_copilot.chart.repository import ChartRepository


def load_dotenv(path: Path = Path(".env")) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if value.strip():
                    os.environ.setdefault(key.strip(), value.strip())


def resolve_participant(query: str) -> str:
    people = ChartRepository(use_embeddings=False).list_participants()
    exact = [p for p in people if p["id"] == query]
    if exact:
        return exact[0]["id"]
    matches = [p for p in people if query.lower() in p["name"].lower()]
    if len(matches) != 1:
        names = ", ".join(p["name"] for p in matches) or "none"
        raise SystemExit(f"Expected one participant matching {query!r}, found: {names}")
    return matches[0]["id"]


async def generate(participant_id: str, config: AgentConfig, in_process: bool):
    llm = LLM()
    if in_process:
        return await run_agent(participant_id, llm, InProcessChartClient(), config)
    async with MCPChartClient() as chart:
        return await run_agent(participant_id, llm, chart, config)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--participant", required=True, help="participant id or part of their name")
    ap.add_argument("--out-dir", type=Path, default=Path("briefs"))
    ap.add_argument("--in-process", action="store_true", help="call the chart tools directly instead of over MCP")
    ap.add_argument("--draft-model", default=AgentConfig.draft_model)
    ap.add_argument("--verify-model", default=AgentConfig.verify_model)
    ap.add_argument("--gather-model", default=AgentConfig.gather_model)
    args = ap.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY in your environment or .env first.")

    config = AgentConfig(draft_model=args.draft_model, verify_model=args.verify_model,
                         gather_model=args.gather_model)
    pid = resolve_participant(args.participant)
    brief = asyncio.run(generate(pid, config, args.in_process))

    args.out_dir.mkdir(exist_ok=True)
    (args.out_dir / f"{pid}.json").write_text(brief.model_dump_json(indent=2))
    markdown = render_markdown(brief)
    (args.out_dir / f"{pid}.md").write_text(markdown)
    print(markdown)


if __name__ == "__main__":
    main()
