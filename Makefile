.PHONY: seed test eval regress verify-audit review replay demo
PROMPT ?= v3
BASE ?= v1
CAND ?= v3
seed:
	uv run python -m ledgerline_crm.seed
test:
	uv run pytest -q
eval:
	uv run python -m evals.run --prompt $(PROMPT)
regress:
	uv run python -m evals.regress --base $(BASE) --candidate $(CAND)
verify-audit:
	uv run python -m review.cli verify-audit
review:
	uv run python -m review.web
replay:
	uv run python -m evals.replay
demo:
	uv run python -m review.demo
	uv run python -m review.web --db local/demo/crm.db --audit local/demo/audit.jsonl
