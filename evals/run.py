"""Live evaluations; reports are generated only from completed SDK runs."""

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone

import yaml
from claude_agent_sdk import ClaudeAgentOptions

from agent.runner import ROOT, append, collect, common_options, run_lead
from evals.graders import grade
from ledgerline_crm.seed import seed
from ledgerline_crm.store import Store

DIMENSIONS = ("grounded", "specificity", "tone", "next_step")


def validate_rubric(output, expected_ids):
    scores = output["scores"]
    indexed = {item["id"]: item for item in scores}
    if len(scores) != len(indexed) or set(indexed) != expected_ids:
        raise ValueError("rubric scenario inventory mismatch")
    for item in scores:
        for dimension in DIMENSIONS:
            value = item[dimension]
            if (
                type(value["score"]) is not int
                or not 1 <= value["score"] <= 5
                or not value["justification"].strip()
            ):
                raise ValueError("invalid rubric score or justification")
    return indexed


def summarize(rows, rubric_result):
    results = [r["result"] for r in rows] + [rubric_result]
    return {
        "scenario_count": len(rows),
        "deterministic_passes": sum(all(r["checks"].values()) for r in rows),
        "rubric_means": {
            d: sum(r["rubric"][d]["score"] for r in rows) / len(rows) for d in DIMENSIONS
        },
        "estimated_cost_usd": sum(r.get("total_cost_usd") or 0 for r in results),
        "tokens": {
            key: sum((r.get("usage") or {}).get(key, 0) for r in results)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        },
    }


def markdown(report):
    lines = [
        f"# {report['prompt_version']} · {report['created_at']}",
        "",
        f"Deterministic: **{report['deterministic_passes']}/{report['scenario_count']}**.",
        f"SDK estimated list-price cost (not subscription charge): **${report['estimated_cost_usd']:.6f}**.",
        "",
        "| Scenario | Route | Deterministic | Failing checks |",
        "|---|---|---|---|",
    ]
    for row in report["scenarios"]:
        failed = [k for k, v in row["checks"].items() if not v]
        lines.append(
            f"| {row['id']} | {row['route']} | {'FAIL' if failed else 'PASS'} | {', '.join(failed) or '—'} |"
        )
    lines += ["", "| Rubric dimension | Mean / 5 |", "|---|---|"]
    lines += [f"| {key} | {value:.3f} |" for key, value in report["rubric_means"].items()]
    lines += [
        "",
        "Tokens (agent sessions + one rubric session): `" + json.dumps(report["tokens"]) + "`.",
        "",
        f"Grader trace: `{report['rubric_trace']}`.",
        "",
        "## Written rubric judgments",
        "",
    ]
    for row in report["scenarios"]:
        lines += [f"### {row['id']}", ""]
        lines += [
            f"- **{d} {row['rubric'][d]['score']}/5**: {row['rubric'][d]['justification']}"
            for d in DIMENSIONS
        ]
        lines.append("")
    return "\n".join(lines) + "\n"


async def rubric(rows, store, trace):
    score = {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "justification": {"type": "string"},
        },
        "required": ["score", "justification"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, **{d: score for d in DIMENSIONS}},
                    "required": ["id", *DIMENSIONS],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["scores"],
        "additionalProperties": False,
    }
    payload = [
        {
            "id": row["id"],
            "expected_route": row["expected_route"],
            "lead": store.rows("SELECT * FROM leads WHERE id=?", (row["id"],))[0],
            "proposal": row["transcript"]["proposals"][0]
            if row["transcript"]["proposals"]
            else None,
            "retrieved_kb": {
                doc["id"]: doc
                for call in row["transcript"]["calls"]
                if call["name"] == "search_knowledge_base"
                for doc in call["result"]
            },
        }
        for row in rows
    ]
    prompt = "Score every id independently in UNTRUSTED_EVIDENCE_JSON:\n" + json.dumps(payload)
    options = ClaudeAgentOptions(
        **common_options(),
        max_turns=3,
        max_budget_usd=1.5,
        system_prompt=(ROOT / "evals/rubric.md").read_text(),
        output_format={"type": "json_schema", "schema": schema},
    )
    append(
        trace,
        {
            "type": "rubric_input",
            "model": "sonnet",
            "system_prompt": options.system_prompt,
            "input": prompt,
        },
    )
    result = await collect(prompt, options, trace)
    output = result.get("structured_output")
    if output is None:
        raise RuntimeError("rubric returned no structured output; see trace")
    return validate_rubric(output, {row["id"] for row in rows}), result


async def evaluate(version, concurrency=3):
    created = datetime.now(timezone.utc)
    stamp = created.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    store = Store()
    seed(store)
    scenarios = [
        yaml.safe_load(path.read_text())
        for path in sorted((ROOT / "evals/scenarios").glob("*.yaml"))
    ]
    if {s["id"] for s in scenarios} != {r["id"] for r in store.rows("SELECT id FROM leads")}:
        raise ValueError("scenario and seed lead inventories differ")
    kb_ids = {r["id"] for r in store.rows("SELECT id FROM kb")}
    semaphore = asyncio.Semaphore(concurrency)
    evidence = ROOT / "evals/fixtures" / f"{stamp}-{version}"
    evidence.mkdir(parents=True)

    async def one(scenario):
        async with semaphore:
            transcript = await run_lead(version, scenario["id"], store)
        checks = grade(scenario, transcript, kb_ids)
        path = evidence / (scenario["id"] + ".json")
        path.write_text(
            json.dumps(
                {"scenario": scenario, "transcript": transcript}, indent=2, ensure_ascii=False
            )
            + "\n"
        )
        full_trace = evidence / (scenario["id"] + ".jsonl")
        shutil.copyfile(ROOT / transcript["trace"], full_trace)
        print(
            f"{version} {scenario['id']}: {'PASS' if all(checks.values()) else 'FAIL'} "
            + ",".join(k for k, v in checks.items() if not v),
            flush=True,
        )
        return {
            "id": scenario["id"],
            "expected_route": scenario["expected_route"],
            "route": transcript["proposals"][0]["route"] if transcript["proposals"] else None,
            "checks": checks,
            "result": transcript["result"],
            "fixture": str(path.relative_to(ROOT)),
            "trace": str(full_trace.relative_to(ROOT)),
            "transcript": transcript,
        }

    # Exceptions (including usage limits) abort report publication; partial traces remain real.
    rows = await asyncio.gather(*(one(s) for s in scenarios))
    rubric_trace = evidence / "rubric.jsonl"
    scores, rubric_result = await rubric(rows, store, rubric_trace)
    for row in rows:
        row["rubric"] = scores[row["id"]]
        del row["transcript"]
    report = {
        "schema_version": 1,
        "created_at": created.isoformat(),
        "prompt_version": version,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "input_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                ROOT / f"agent/prompts/{version}.md",
                ROOT / "evals/rubric.md",
                ROOT / "evals/graders.py",
                ROOT / "data/seed.json",
                ROOT / "agent/runner.py",
                ROOT / "mcp_server/server.py",
                ROOT / "ledgerline_crm/store.py",
                ROOT / "evals/run.py",
                ROOT / "pyproject.toml",
                ROOT / "uv.lock",
                *sorted((ROOT / "evals/scenarios").glob("*.yaml")),
            ]
        },
        "rubric_trace": str(rubric_trace.relative_to(ROOT)),
        "rubric_result": rubric_result,
        "scenarios": rows,
        **summarize(rows, rubric_result),
    }
    path = ROOT / "evals/reports" / f"{stamp}-{version}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    path.with_suffix(".md").write_text(markdown(report))
    print(
        f"REPORT {path.relative_to(ROOT)}\n"
        + json.dumps(
            {
                k: report[k]
                for k in (
                    "deterministic_passes",
                    "scenario_count",
                    "rubric_means",
                    "tokens",
                    "estimated_cost_usd",
                )
            },
            indent=2,
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["v1", "v2", "v3"], required=True)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.prompt, args.concurrency))
    raise SystemExit(0 if result["deterministic_passes"] == result["scenario_count"] else 1)


if __name__ == "__main__":
    main()
