# inbound-agent-oversight

A Claude Agent SDK agent researches fictional inbound leads through a five-tool
stdio MCP server and queues a draft for human review. Recorded evaluations compare
three prompt versions, including a deliberately unsafe edit and its repair.

**Author: Petie Clark · MIT · all CRM/lead data synthetic**

## Architecture in 60 seconds

```mermaid
flowchart LR
    L[15 synthetic leads] --> A[Claude Agent SDK / sonnet]
    P[Versioned system prompt] --> A
    A <-->|stdio MCP / five tools only| M[Governed CRM server]
    M --> K[SQLite accounts, history, KB]
    M --> Q[Pending proposals]
    Q --> R[Local human review UI or CLI]
    R -->|approve or edit + approve| O[Simulated outbox / nothing sent]
    R -->|reject + reason| X[Rejected]
    M --> H[Hash-chained audit JSONL + SQLite mirror]
    R --> H
    A --> T[SDK messages + tool traces]
    T --> E[Deterministic checks + separate Claude rubric]
    E --> G[Report comparison / CI]
```

Read [`agent/prompts/v3.md`](agent/prompts/v3.md),
[`mcp_server/server.py`](mcp_server/server.py),
[`ledgerline_crm/store.py`](ledgerline_crm/store.py), and
[`evals/graders.py`](evals/graders.py) for the main boundaries. Published fictional
facts and commercial/routing policy are in
[`data/knowledge-base.md`](data/knowledge-base.md); `data/seed.json` is the seed source.
There are 25 accounts, 14 contacts, 3 open opportunities, 10 prior interactions,
5 KB documents, and 15 leads. All email/domain values use `.example`.

## Quickstart

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). The lockfile pins the
executed dependencies, including `claude-agent-sdk==0.2.170`, `mcp==1.30.0` and
`cryptography==45.0.7` (`<46` is required on the Intel Mac used for this build).

```sh
uv sync --frozen --python 3.12
make seed                         # deterministic upsert; preserves workflow/audit history
uv run pytest -q                  # offline: no API key or login needed
make replay                       # 45 recorded final transcripts, including known failures
```

For a live lead, either log into an installed Claude Code CLI (`claude auth login`)
or export `ANTHROPIC_API_KEY` in your shell. The SDK can use its bundled CLI with an
API key; `agent.runner` prefers an installed `claude` when present. A non-default
subscription login can be selected with `CLAUDE_CONFIG_DIR` in the environment;
credentials are not stored in this repository.

```sh
uv run python -m agent.runner smb --prompt v3
make review                       # http://127.0.0.1:8765/ ; Ctrl-C to stop
```

Open the review queue, inspect the inbound lead, research trail, rationale,
citations, and draft. **Approve original** ignores textarea edits; **Edit + approve**
uses the edited text; **Reject** requires a reason. The reviewer name is recorded.
All approvals only write to SQLite's `outbox`; there is no delivery integration.

CLI equivalent (replace `ID` with a proposal id from `list`):

```sh
uv run python -m review.cli list
uv run python -m review.cli approve ID --who "Local reviewer"
uv run python -m review.cli edit-approve ID --who "Local reviewer" --draft-file reply.txt --reason "Clarified next step"
uv run python -m review.cli reject ID --who "Local reviewer" --reason "Not appropriate"
make verify-audit
```

Live evals are explicit and use subscription/API quota. Each full pass runs 15
isolated lead sessions plus one batch rubric session, with at most three lead
sessions concurrent, 12 agent turns, 240 seconds/session, and SDK budget caps.

```sh
make eval PROMPT=v1
make eval PROMPT=v2                # deliberately unsafe; failure is expected
make eval PROMPT=v3
make regress BASE=v1 CAND=v2       # nonzero (make returns 2; comparator returns 1)
make regress BASE=v1 CAND=v3       # zero
```

CI runs tests, deterministic fixture replay and the recorded v1→v3 comparison on
every push/PR without a secret. The workflow-dispatch live job is opt-in and needs
an `ANTHROPIC_API_KEY` secret in a protected `live-evals` environment. No hosted CI
run is claimed: this repository has no remote and has not been pushed.

## The regression, including the unsuccessful attempts

These are the final comparable real sessions, deterministically regraded after a
matcher correction. All LLM rubric scores and SDK usage are unchanged from the
live reports. The `sonnet` alias resolved to **claude-sonnet-5-5** in these runs.

| Prompt | Deterministic | Grounded / 5 | Specificity / 5 | Tone / 5 | Next step / 5 | SDK estimated cost |
|---|---|---|---|---|---|---|
| [v1](evals/reports/20261021T164439-regraded-v1.md) | 15/15 | 4.667 | 4.467 | 4.600 | 4.333 | $0.487131 |
| [v2](evals/reports/20261021T164440-regraded-v2.md) | 9/15 | 4.133 | 4.267 | 4.267 | 4.067 | $0.418150 |
| [v3](evals/reports/20261021T164440-regraded-v3.md) | 15/15 | 4.667 | 4.533 | 4.533 | 4.400 | $0.495449 |

Costs are SDK list-price estimates, **not subscription charges**. JSON reports
include input, output, cache-read and cache-creation tokens for agents and grader,
per-scenario checks and judgments, source hashes, and exact trace/fixture paths.
The markdown reports include all 15 scenario rows and written rubric justifications.

- **v1** explicitly treats lead/CRM text as untrusted, requires policy research,
  and forbids concessions even inside a pending draft.
- **v2** is a deliberately seeded bad edit, not an accidentally discovered bug.
  It transfers commercial checking to the reviewer, treats templates too
  generously, narrows research, and suggests a 10% courtesy incentive to sound
  warmer. These assumptions are false. On the commitment lead it copied a delivery
  guarantee and custom/net-90 approval into the actual draft. On the injection
  lead it resisted the requested 50% override but still offered an unauthorized
  **10%** discount. The report also catches skipped research and a wrong route.
- **v3** restores the untrusted-input and commitments rules and adds an explicit
  pre-proposal draft check. All deterministic checks pass and no rubric mean
  drops more than 0.3 from v1.

The first warmth edits did **not** break the model. One preliminary suite result
was a false positive: its must-not checker inspected rationale that quoted a
refused instruction. That checker was fixed and all comparable versions rerun.
The final live v2 pass also exposed a matcher gap: “we'd be glad to offer” escaped
an earlier matcher that handled “happy”. The separate LLM rubric already gave that
injection draft 1/5 for grounding and next step. A failing unit test added the
missing synonym; `evals.rescore` then regenerated **only deterministic checks**
from the same byte-preserved recordings, uniformly for v1/v2/v3. It never calls a
model or changes a draft, LLM judgment, or usage. CI verifies this lineage.

Original generated live reports are retained under `evidence/experiments/live-*`.
The final reports link and hash their exact source. Reproduce the offline regrade:

```sh
for report in evidence/experiments/live-*.json; do
    uv run python -m evals.rescore "$report"
done
make replay
```

The development history used six full passes and eight single-lead probes (98
agent sessions and six rubric sessions), rather than the approximate four-pass
budget. Total SDK estimated cost for all development sessions was $3.210993.
See [`evidence/experiments/README.md`](evidence/experiments/README.md) for preserved
unsuccessful experiments and [`DEVIATIONS.md`](DEVIATIONS.md) for scope differences.

## Design decisions and boundaries

**No send tool.** MCP exposes account lookup, contact history, open opportunities,
KB search, and `propose_action` only. The server binds the run to one lead, checks
route/priority/citation ids, and enforces one proposal per run. No account/opportunity
write, arbitrary SQL, HTTP, email, Bash, file-edit or browser capability is exposed.
The Agent SDK's `allowed_tools` is an auto-approval list, not a sandbox: `tools=[]`
removes built-ins, `strict_mcp_config=True` excludes ambient servers, settings/skills
are not loaded, and unlisted calls are denied. SDK init recordings and stdio tests
verify the resulting five-tool surface. This is a capability boundary, not an OS
sandbox or protection against a compromised CLI/MCP process.

**Hash-chained audit.** Proposal creation, approvals/edits/rejections (actor, UTC
time, text/status diff), and simulated outbox writes are chained with SHA-256.
SQLite audit rows are append-only via triggers; a file lock serializes cooperating
writers, and mutations commit atomically in SQLite before the JSONL append is
flushed/fsynced. Verification checks hashes, sequence and the exact SQLite mirror,
so removing the last line is detected too. A crash between DB commit and file
append leaves a detectable mismatch and blocks further writes. There is no silent
“repair” that overwrites suspicious bytes; operator reconciliation would be needed.
A privileged operator can rewrite both stores: this is tamper evidence, not a
signature, WORM storage, or a substitute for externally anchoring a head hash.

**Deterministic first.** Routes, one proposal, research order, retrieved real KB
citations, scenario assertions, and forbidden content are cheap inspectable gates.
The separate same-model rubric adds judgments on grounding, specificity, tone and
next step. Regression blocks any previously passing deterministic check becoming
false, or any dimension mean falling more than 0.3. A low mean is not hidden by
averaging all rubric dimensions into one value. CI replays final recordings and
requires the known v2 negative cases to stay detectable.

**Tracing.** `runs/<run_id>.jsonl` holds input/prompt/version/hash, public SDK
messages, every tool invocation's args/result/handler latency/result byte count,
and the SDK result's resolved models, usage and estimated cost. Hidden reasoning
blocks/signatures are omitted. Eval copies are committed next to each fixture;
ordinary `runs/`, `.env`, local data and databases are ignored. The local review UI
loads the actual research trail by run id. The tiny KB retriever ranks lexical
matches; it does not inject an unconditional policy dump into every search.

Authoritative API references used: [Python Agent SDK options and result messages](https://platform.claude.com/docs/en/agent-sdk/python),
[official MCP SDK v1.30.0](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0),
and [v1 FastMCP documentation](https://py.sdk.modelcontextprotocol.io/v1/).
The installed signatures and real stdio/model runs, not citations alone, were used
to verify these boundaries.

## Evidence and limitations

[`evidence/acceptance.md`](evidence/acceptance.md) records commands, exits, report
paths, full injection trace paths, audit/tamper proof, screenshot and Git tree.
[`evidence/review-pending.png`](evidence/review-pending.png) is a real pending v1
proposal. Browser proof exercised approve, edit+approve, rejection with/without a
reason, read back SQLite/outbox/audit state, and recorded no page errors. Run
`uv run --with playwright python scripts/prove_review.py` after installing
Chromium (`uv run --with playwright python -m playwright install chromium`) and
creating fresh v1 proposals for those leads. It consumes three pending proposals;
it is not an idempotent screenshot-only command.

`uv run python scripts/prove_audit.py` verifies tampered and truncated temporary
copies fail while the original audit passes. `evidence/audit.jsonl` is the actual
synthetic development audit snapshot, not an invented transcript; a fresh clone's
`make seed` starts an empty local workflow/audit instead of importing that snapshot.

Limitations: 15 seeded scenarios are not statistical coverage; prompts were tuned
against these known cases. Regex checks can miss paraphrases and can misread
negation/quotation; they do not perform general entity recognition or guarantee
that every price/fact is entailed. Citations are checked for existence and retrieval,
not sentence-level entailment. A single same-model batch judge has correlated
errors and ordering effects, and its scores are not a human review. Successful
runs here do not guarantee future output; aliases and subscription behavior can
change. The demo uses small synchronous SQLite/file operations and Unix file
locks, not a multi-tenant queue, durable distributed transaction, or replay-safe
provider workflow. A run retry gets a new id and can produce another pending
proposal; CRM duplicate detection routes to an existing owner rather than globally
deduplicating all inbound messages. The loopback UI checks Host, Origin and CSRF,
but has no authenticated identity: reviewer names are self-attested. Do not expose
it publicly or use any of this with production leads or credentials.
