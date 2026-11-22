"""Run the agent across the answer keys and score every brief.

    # Live run against Claude (costs money; use --limit while iterating)
    python -m idt_copilot.evals.run_evals --limit 5
    python -m idt_copilot.evals.run_evals                     # all 40

    # Re-score briefs from an earlier run (free, no API calls) — this is what CI does
    python -m idt_copilot.evals.run_evals --briefs-dir evals/runs/<run>/briefs

    # Fail (exit 1) if quality drops below a bar
    python -m idt_copilot.evals.run_evals --briefs-dir ... --min-recall 0.9 --max-distractor-violations 0

Each run writes evals/runs/<timestamp>/ with briefs/, results.json, and report.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from idt_copilot.agent.chart_client import InProcessChartClient, MCPChartClient
from idt_copilot.agent.graph import AgentConfig, run_agent
from idt_copilot.agent.llm import LLM
from idt_copilot.agent.schema import Brief
from idt_copilot.evals.score import ParticipantScore, as_dict, failed_score, score_brief, summarize
from idt_copilot.models import AnswerKey


def load_keys(golden_dir: Path) -> list[AnswerKey]:
    return [AnswerKey.model_validate_json(p.read_text()) for p in sorted(golden_dir.glob("*.json"))]


async def generate_briefs(keys: list[AnswerKey], out_dir: Path, config: AgentConfig, concurrency: int,
                          use_mcp: bool, make_llm=LLM) -> dict[str, Brief | Exception]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, Brief | Exception] = {}

    async def one(key: AnswerKey):
        async with sem:
            try:
                llm = make_llm()  # one per participant so cost and tokens are per brief
                if use_mcp:
                    async with MCPChartClient() as chart:
                        brief = await run_agent(key.participant_id, llm, chart, config)
                else:
                    brief = await run_agent(key.participant_id, llm, InProcessChartClient(), config)
                (out_dir / f"{key.participant_id}.json").write_text(brief.model_dump_json(indent=2))
                results[key.participant_id] = brief
                print(f"  done  {brief.participant_name}")
            except Exception as e:  # keep going; a failed brief scores zero and is reported
                results[key.participant_id] = e
                print(f"  ERROR {key.participant_id}: {e}")

    await asyncio.gather(*(one(k) for k in keys))
    return results


def score_all(keys: list[AnswerKey], briefs: dict[str, Brief | Exception]) -> list[ParticipantScore]:
    scores = []
    for key in keys:
        b = briefs.get(key.participant_id)
        if isinstance(b, Brief):
            scores.append(score_brief(b, key))
        else:
            scores.append(failed_score(key, str(b) if b else "no brief"))
    return scores


def render_report(summary: dict, scores: list[ParticipantScore], label: str) -> str:
    s = summary
    lines = [
        f"# Eval report: {label}", "",
        "All participants and answer keys are synthetic.", "",
        "| Metric | Value |", "| --- | --- |",
        f"| Briefs scored | {s['participants']} ({s['errors']} errors) |",
        f"| Recall: answer-key items caught | {s['recall']:.1%} |",
        f"| High-severity recall | {s['high_severity_recall']:.1%} |",
        f"| Briefs that caught everything | {s['perfect_briefs']} of {s['participants']} |",
        f"| Old events reported as new | {s['distractor_violations']} |",
        f"| Items per brief | {s['items_per_brief']} |",
        f"| Items not tied to an answer-key item | {s['extra_item_rate']:.1%} |",
        f"| Claims removed by the verifier | {s['removed_claims']} |",
        f"| Items flagged partially supported | {s['partially_supported_items']} |",
        f"| Cost per brief | ${s['cost_usd_per_brief']:.3f} (total ${s['cost_usd_total']:.2f}) |",
        f"| Time per brief | {s['seconds_median']}s median, {s['seconds_p90']}s p90 |",
        "", "## Recall by category", "", "| Category | Caught | Recall |", "| --- | --- | --- |",
    ]
    lines += [f"| {c} | {v['caught']} of {v['total']} | {v['recall']:.0%} |"
              for c, v in s["recall_by_category"].items()]
    misses = [(sc, m) for sc in scores for m in sc.missed]
    if misses:
        lines += ["", "## Missed items", ""] + [f"- `{sc.participant_id[:8]}` {m}" for sc, m in misses]
    viol = [(sc, v) for sc in scores for v in sc.distractor_violations]
    if viol:
        lines += ["", "## Old events reported as new", ""] + [f"- `{sc.participant_id[:8]}` {v}" for sc, v in viol]
    errs = [sc for sc in scores if sc.error]
    if errs:
        lines += ["", "## Errors", ""] + [f"- `{sc.participant_id[:8]}` {sc.error}" for sc in errs]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from idt_copilot.agent.run import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden-dir", type=Path, default=Path("data/golden"))
    ap.add_argument("--runs-dir", type=Path, default=Path("evals/runs"))
    ap.add_argument("--briefs-dir", type=Path, help="score saved briefs instead of running the agent")
    ap.add_argument("--limit", type=int, help="only the first N participants")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--mcp", action="store_true", help="reach the chart over MCP stdio (slower)")
    ap.add_argument("--draft-model", default=AgentConfig.draft_model)
    ap.add_argument("--verify-model", default=AgentConfig.verify_model)
    ap.add_argument("--gather-model", default=AgentConfig.gather_model)
    ap.add_argument("--min-recall", type=float)
    ap.add_argument("--min-high-recall", type=float)
    ap.add_argument("--max-distractor-violations", type=int)
    args = ap.parse_args(argv)

    keys = load_keys(args.golden_dir)
    if args.limit:
        keys = keys[: args.limit]

    if args.briefs_dir:
        run_dir = args.briefs_dir.parent
        briefs: dict = {}
        for k in keys:
            path = args.briefs_dir / f"{k.participant_id}.json"
            if path.exists():
                briefs[k.participant_id] = Brief.model_validate_json(path.read_text())
        keys = [k for k in keys if k.participant_id in briefs]
        label = f"re-scored {args.briefs_dir}"
    else:
        run_dir = args.runs_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
        config = AgentConfig(draft_model=args.draft_model, verify_model=args.verify_model,
                             gather_model=args.gather_model)
        print(f"Running the agent on {len(keys)} participants...")
        briefs = asyncio.run(generate_briefs(keys, run_dir / "briefs", config, args.concurrency, args.mcp))
        label = f"{run_dir.name} · draft {config.draft_model} · verify {config.verify_model}"

    scores = score_all(keys, briefs)
    summary = summarize(scores)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(
        {"summary": summary, "participants": [as_dict(s) for s in scores]}, indent=2))
    report = render_report(summary, scores, label)
    (run_dir / "report.md").write_text(report)
    print(report)

    failures = []
    if args.min_recall is not None and summary["recall"] < args.min_recall:
        failures.append(f"recall {summary['recall']} < {args.min_recall}")
    if args.min_high_recall is not None and summary["high_severity_recall"] < args.min_high_recall:
        failures.append(f"high-severity recall {summary['high_severity_recall']} < {args.min_high_recall}")
    if args.max_distractor_violations is not None and \
            summary["distractor_violations"] > args.max_distractor_violations:
        failures.append(f"{summary['distractor_violations']} distractor violations")
    if failures:
        print("FAILED quality bar: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
