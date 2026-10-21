"""One isolated SDK session and one lead-bound stdio server per run."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from ledgerline_crm.store import Store
from mcp_server.server import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]


def append(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def lead_prompt(lead):
    return (
        "LEAD_JSON (one JSON object):\n"
        + json.dumps(lead, ensure_ascii=False)
        + "\nEND_LEAD_JSON\nTriage this lead and queue one proposal."
    )


def common_options():
    # Caller chooses CLI profile via env. No machine-specific account paths in public code.
    env = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["CLAUDE_CONFIG_DIR"]
    return dict(
        model="sonnet",
        tools=[],
        setting_sources=[],
        skills=[],
        permission_mode="dontAsk",
        strict_mcp_config=True,
        cli_path=shutil.which("claude"),
        cwd=ROOT,
        env=env,
        effort="low",
        thinking={"type": "disabled"},
        extra_args={"no-session-persistence": None, "disable-slash-commands": None},
    )


def agent_options(version, lead_id, run_id, trace, db_path, audit_path):
    prompt_path = ROOT / "agent/prompts" / f"{version}.md"
    if version not in {"v1", "v2", "v3"}:
        raise ValueError("unknown prompt version")
    return ClaudeAgentOptions(
        **common_options(),
        max_turns=12,
        max_budget_usd=1.5,
        allowed_tools=[f"mcp__crm__{name}" for name in TOOL_NAMES],
        system_prompt=prompt_path.read_text(),
        mcp_servers={
            "crm": {
                "type": "stdio",
                "command": sys.executable,
                "args": [
                    "-m",
                    "mcp_server.server",
                    "--db",
                    str(Path(db_path).resolve()),
                    "--audit",
                    str(Path(audit_path).resolve()),
                    "--run-id",
                    run_id,
                    "--lead-id",
                    lead_id,
                    "--trace",
                    str(trace.resolve()),
                ],
            }
        },
    )


async def collect(prompt, options, trace):
    final = None
    async with asyncio.timeout(240):
        async for message in query(prompt=prompt, options=options):
            # Save public SDK message stream, never hidden reasoning blocks/signatures.
            payload = asdict(message) if is_dataclass(message) else {"value": str(message)}
            if "content" in payload and isinstance(payload["content"], list):
                payload["content"] = [b for b in payload["content"] if "thinking" not in b]
            if payload.get("subtype") == "init":
                # Init may include host identity/path diagnostics; retain relevant capabilities only.
                data = payload.get("data", {})
                payload = {
                    "subtype": "init",
                    "data": {
                        k: data[k]
                        for k in ("model", "tools", "mcp_servers", "permissionMode")
                        if k in data
                    },
                }
            append(
                trace, {"type": "sdk", "message_type": type(message).__name__, "message": payload}
            )
            if isinstance(message, ResultMessage):
                final = payload
    if final is None:
        raise RuntimeError("SDK stream ended without ResultMessage")
    if final["is_error"]:
        raise RuntimeError(f"SDK error: {final.get('result') or final.get('subtype')}")
    return final


async def run_lead(version, lead_id, store, run_dir=ROOT / "runs"):
    run_id = f"{version}-{lead_id}-{uuid.uuid4().hex[:12]}"
    trace = Path(run_dir) / f"{run_id}.jsonl"
    lead = store.rows("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise ValueError("unknown lead")
    options = agent_options(version, lead_id, run_id, trace, store.db_path, store.audit_path)
    append(
        trace,
        {
            "type": "run",
            "run_id": run_id,
            "lead_id": lead_id,
            "prompt_version": version,
            "model": options.model,
            "prompt_sha256": hashlib.sha256(options.system_prompt.encode()).hexdigest(),
            "system_prompt": options.system_prompt,
            "input": lead_prompt(lead[0]),
        },
    )
    try:
        result = await collect(lead_prompt(lead[0]), options, trace)
    except Exception as exc:
        append(trace, {"type": "error", "error": str(exc)})
        raise
    records = [json.loads(line) for line in trace.read_text().splitlines()]
    calls = [e for e in records if e["type"] == "tool"]
    return {
        "run_id": run_id,
        "trace": str(trace.relative_to(ROOT)),
        "calls": calls,
        "proposals": store.proposals(run_id),
        "result": result,
        "runtime_ok": len(store.proposals(run_id)) == 1,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lead_id")
    parser.add_argument("--prompt", choices=["v1", "v2", "v3"], default="v3")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_lead(args.prompt, args.lead_id, Store())), indent=2))


if __name__ == "__main__":
    main()
