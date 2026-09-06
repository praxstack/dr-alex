# Repair and subagent evaluation - 2026-09-06

Status: software regression gate PASS; evaluation matrix retained for ongoing checks.
The original persona and golden crisis corpus hashes are unchanged. A concurrent
AGENTS skill-discovery edit is preserved unstaged, outside this repair.

## Active route

```text
Room / Hermes therapist Desktop / therapist gateway
    -> paired local Dr. Alex API (127.0.0.1:18787)
    -> durable input + deterministic triage
       RED -> static card; no retrieval/model
       other -> books + bounded raw historical excerpts
             -> isolated Codex subscription transport (gpt-5.6-sol, zero tools)
             -> output gates -> durable response -> client
```

## Measured matrix

| Worker/task | Requested / observed | Original result | Current result | Acceptance |
|---|---|---|---|---|
| Grok patch review | grok-4.6 / xhigh, both observed in session metadata | 2/4 checks pass | 2 API-contract/coverage failures retained | Not accepted as a clean review |
| Grok corrected safety checks | grok-4.6 / xhigh, both observed | Frozen supplied source: 1/3 pass | Candidate: 2/3 pass | Two safety checks accepted; whitespace assertion rejected with original preserved |
| Grok backup review | grok-4.6 / xhigh, both observed | Retention/journal/linked-file misses reproduced | Eight backup checks pass after fixes | Accepted reproduced findings; rejected directory-symlink claim |
| Lifecycle implementation | Luna | Eight independent defects found across two review passes | All eight independent reproductions now pass | PASS |
| Historical recall | Luna | No raw-history bridge | Six synthetic checks pass | Local pass; native client integration passed |
| Hermes retention/maintenance | Implementation agent | Only 5/13 imports; missing job wrappers | 13 imports / 222 messages, all pinned; five real jobs report success | Verified DB counts and integrity; receipts under Clinical repair directory |
| Codex transport | Implementation agent + parent | Claude required, unavailable subscription | Actual synthetic Codex completions pass; containment and entrypoint checks pass | Native isolated client GREEN/RED smoke passed |
| Independent lifecycle review | Separate reviewer | Eight synthetic failure reproductions | Original five plus later three pass independently | PASS |

`agent-evaluation.json` contains the machine-readable status. Original Grok prompts,
outputs and checks remain here. Tests are inspected before execution. The accepted
Grok safety checks are also in `tests/test_grok_gate_regression.py`.

## Grok evaluation findings

The first review lacked complete function bodies and guessed the callback API. Its
high-severity boundary claim was conditional and unsupported by the actual function.
The second prompt included the full source and exact contract. It reproduced two
missing dependency alternatives; both are now blocked. Its remaining failed check
expects `; ;`, while citation cleanup returns `;;`; the empty cell and its neighboring
content remain present. Product behavior was not changed to satisfy that assertion.

The evaluation remains available for regression checks. The production authenticated
model probe and readiness endpoint both passed using Codex on September 6 at 11:50 UTC.
Native Hermes integration also passed with synthetic context; real clinical content was
not sent for testing. Same-machine restore checks cannot prove recovery after Keychain loss.

Final full suite: **650 passed, 2 skipped**, 8.87 seconds. Ruff clean.
Grok model-turn elapsed times: first review 719.1s, corrected checks 248.3s, backup review 331.8s.
These are measured observations, not a claim that X-high is always the fastest option.

Packaging verification: wheel and source archive build successfully; Room assets occur
once and only the two crisis-card seeds are bundled from data/. Run
`python tools/check-package.py <wheel> <sdist>` after `uv build`. The original
Grok patch prompt retains six whitespace-only diff-context lines byte-for-byte.
