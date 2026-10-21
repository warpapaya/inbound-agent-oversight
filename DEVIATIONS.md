# Deviations and disclosed implementation choices

The frozen `CONTRACT.md` was not edited. Its SHA-256 remains
`6713af4641326a8bd6b7e169b2a38205180612dde147fe77defb8660ffc551e4`.

1. **Live budget:** six complete 15-lead passes plus eight single-lead probes were
   executed (98 agent sessions, six rubric sessions), instead of approximately
   four complete passes. The extra work avoided presenting false positives or
   resistant-model behavior as a successful catch. All-development SDK list-price
   estimate: $3.210993; this is not a subscription billing claim.
2. **Regression strength:** dropping the original instructions alone did not
   induce the requested bad behavior. Final v2 is a stronger deliberately unsafe
   “warm concise draft” edit: it delegates commercial validation to reviewers,
   assumes templates are pre-approved, and adds an unapproved 10% courtesy incentive.
   The direct 50% prompt injection remained resisted. The injection scenario still
   genuinely regressed because the draft offered 10%; the commitment scenario
   copied a delivery guarantee and net-90/custom-term approval. This is a seeded
   negative prompt, not an organically discovered production regression.
3. **Report lineage:** the final comparable live v1/v2/v3 sessions are preserved in
   `evidence/experiments/live-*.json` with their raw generated markdown and full
   fixtures/traces. A regex vocabulary miss (“glad” versus “happy”) was corrected
   through a failing test, then `evals.rescore` regenerated deterministic checks
   on all three unchanged recordings without new model calls. Final reports under
   `evals/reports/*-regraded-v*.json` identify and hash the originals, keep the exact
   real SDK usage and LLM scores, and are verified by CI. No report was hand-edited.
4. **Rubric batching:** the separate sonnet rubric evaluates all 15 independent
   scenarios in one structured-output call per pass, rather than one grader call
   per lead. All four dimensions have individual scores and written justifications.
5. **Temporary paths:** early pytest executions used macOS's default temporary
   location before the terminal's TMPDIR was explicitly corrected. Subsequent
   tests/proof probes use the designated scratch directory. No production state
   or credentials were put in those temporary test stores.
6. **CI execution:** the workflow is implemented and its offline commands pass
   locally. Hosted GitHub CI was not run, since creating a remote or pushing is
   prohibited. No remote was created and nothing was pushed.

All data is synthetic; no messages were sent. The outbox contains only local
simulated approvals from the real browser proof. The approval UI deliberately
uses self-attested reviewer names rather than production authentication.
