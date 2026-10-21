"""Governed stdio MCP. No transport or API exists for sending a message."""

import argparse
import json
import time
from functools import wraps
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ledgerline_crm.store import Store

TOOL_NAMES = (
    "lookup_account",
    "get_contact_history",
    "find_open_opportunities",
    "search_knowledge_base",
    "propose_action",
)


def build_server(store, run_id, bound_lead, trace_path):
    server = FastMCP("ledgerline-crm")

    def exposed(fn):
        @wraps(fn)
        def traced(*args, **kwargs):
            started = time.perf_counter()
            result, error = None, None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                if trace_path:
                    import inspect

                    arguments = dict(inspect.signature(fn).bind(*args, **kwargs).arguments)
                    event = dict(
                        type="tool",
                        name=fn.__name__,
                        args=arguments,
                        result=result,
                        error=error,
                        result_bytes=len(json.dumps(result).encode()),
                        latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    )
                    # One process owns tool events; each event is one O_APPEND write.
                    with Path(trace_path).open("a") as stream:
                        stream.write(json.dumps(event, ensure_ascii=False) + "\n")

        server.tool()(traced)
        return traced

    @exposed
    def lookup_account(domain: str | None = None, name: str | None = None) -> list[dict]:
        """Find an account by exact domain or name. Never returns private internal notes."""
        return store.lookup_account(domain, name)

    @exposed
    def get_contact_history(email: str) -> list[dict]:
        """Read sanitized prior interactions for a contact."""
        return store.get_contact_history(email)

    @exposed
    def find_open_opportunities(account_id: str) -> list[dict]:
        """Read existing open opportunities and their named owners; do not create duplicates."""
        return store.find_open_opportunities(account_id)

    @exposed
    def search_knowledge_base(query: str) -> list[dict]:
        """Retrieve published product facts and commercial/routing policy with citation IDs."""
        return store.search_knowledge_base(query)

    @exposed
    def propose_action(
        lead_id: str,
        route: Literal[
            "sales_reply", "route_to_ae", "support_handoff", "disqualify", "needs_human"
        ],
        priority: Literal["low", "normal", "high"],
        draft_reply: str,
        rationale: str,
        citations: list[str],
    ) -> dict:
        """Queue exactly one pending draft for the bound lead. This never sends anything."""
        if lead_id != bound_lead:
            raise ValueError("lead does not match this run")
        return store.propose(run_id, lead_id, route, priority, draft_reply, rationale, citations)

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="local/crm.db")
    parser.add_argument("--audit", default="local/audit.jsonl")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    build_server(Store(args.db, args.audit), args.run_id, args.lead_id, args.trace).run(
        transport="stdio"
    )


if __name__ == "__main__":
    main()
