# CHP divergences across shipped ports

Findings from reading five implementations that all call themselves "CHP", surveyed
2026-07-30 while writing [CHP-v1.0.md](CHP-v1.0.md). Every item below was read out of a
real file — file and symbol cited — not inferred.

Each divergence has a conformance vector, so it becomes a CI failure rather than a
comment. Reproduce with:

```bash
python3 spec/conformance/run_conformance.py \
  --adapter-cmd "python3 spec/conformance/adapters/legacy_divergence_adapter.py"
```

## Implementations surveyed

| Repo | File | Profile |
|---|---|---|
| `Consensus-Hardening-Protocol-The-Differ` | `src/cme/chp/` | A (canonical) |
| `convergence` | `src/convergence/chp/` | A |
| `agent-conductor` | `engine/vendor/cme/chp/` (vendored) | A |
| `cognitrader-bsc` | `src/chp/gate.ts` | B |
| `courtvision-ai` | `src/courtvision/chp/gate.py` | B |
| `clearance` | `src/lib/chp.ts` | B (mixed vocabulary) |

---

## Severity 1 — silently weakens a documented control

### D-A1 · Domain foundation floors were never enforced

`Consensus-Hardening-Protocol-The-Differ/src/cme/chp/foundation.py:7`

```python
def foundation_verdict(attack: FoundationAttack) -> Verdict:
    return Verdict.PASS if attack.foundation_score >= 70 else Verdict.REFRAME
```

`.chp/STATE_MACHINE.md` documents three floors — 70 general, **100 finance/CFO**, 85
blockchain/DeFi. The function takes no `domain` argument and hardcodes 70, so every
domain was gated at 70. A finance decision scoring 70 passed a gate documented as
requiring 100.

`convergence/src/convergence/chp/accuracy.py` implements the CFO floor of 100 separately,
so behaviour depended on which repo's code path a decision happened to travel through.

**Spec:** §5.3 — floors are domain-parameterised, unknown domains fall back to 70.
**Vectors:** `A/floor/*`, `A/foundation/finance-70-reframes-regression`.

### D-B5 · Human approval bypassed the confidence check

`cognitrader-bsc/src/chp/gate.ts` → `approveHuman()`

The approval path re-checks only `maxNotionalUsd` and the daily cap. It does not re-run
`adversarialCheck()`, so `min-confidence`, the `HOLD` guard, and the finite-notional
sanity check are all skipped.

Consequence: an action blocked by `evaluate()` for low confidence is **LOCKED and
allowed** once a human approves it. The conformance run shows this precisely:

```
✗ B/approve/approval-cannot-bypass-low-confidence
    expected: state=BLOCKED  allowed=False
    actual:   state=locked   allowed=True
```

A human approval was intended as permission to cross the HITL threshold; it became a
blanket policy override. `courtvision-ai`'s `approve()` re-runs the full sanity check and
is correct.

**Spec:** §6.5 — `approve_human` MUST re-run the full evaluation.
**Vector:** `B/approve/approval-cannot-bypass-low-confidence`.

---

## Severity 2 — breaks cross-implementation verification

### D-B1 · Audit hashes are not comparable across ports

| Port | Canonicalisation |
|---|---|
| `cognitrader-bsc` | `JSON.stringify({action, state, claims, timestamp})` — insertion order, no sorting |
| `courtvision-ai` | `json.dumps(canonical, sort_keys=True)` — sorted |

The same logical decision produces different digests in each. Any cross-system
verification, reconciliation, or shared ledger silently fails. Python's `json.dumps` also
escapes non-ASCII by default while `JSON.stringify` emits it literally, so a rationale
containing "café" diverges even when key order matches.

**Spec:** §3.1 — recursive key sort, no whitespace, literal UTF-8.
**Vectors:** `canon/key-order-independence-*`, `canon/unicode-preserved`, `canon/nested-sorting`.

### D-B3 · Hashed field sets differ, and include wall-clock time

`cognitrader-bsc` hashes the whole action object plus the full claims array **and
`timestamp`**. `courtvision-ai` hashes a flat field list plus violation `rule_id`s and
also includes `timestamp`.

Including a timestamp makes the hash unreproducible: re-evaluating the same decision one
second later yields a different digest, so the hash cannot function as a content
identifier at all.

**Spec:** §6.6 — fixed normative field set; `timestamp` and `decision_id` recorded
alongside the hash, never inside it.
**Vectors:** every `B/evaluate/*` compares `content_hash`.

### D-B2 · State casing differs

`courtvision-ai/src/courtvision/chp/gate.py` → `GateState` uses lowercase (`"locked"`,
`"hitl_required"`). `cognitrader-bsc`, `clearance`, and both Profile A ports use
uppercase. Any consumer matching on state string breaks across the boundary.

**Spec:** §4.1 — UPPERCASE on the wire.
**Vectors:** every `B/evaluate/*` and `B/approve/*` compares `state`.

---

## Severity 3 — semantic drift worth fixing

### D-B4 · Daily-cap window semantics differ

`cognitrader-bsc` uses a rolling 24h window anchored to `dailyWindowStart`, initialised at
gate construction and reset when 24h elapses. `courtvision-ai` keys a dict by UTC calendar
day.

Under the rolling window the available budget depends on process start time. The same
action sequence passes on a host started at 09:00 and is blocked on one started at 23:00,
and an auditor cannot reproduce either result. The calendar day is reproducible and matches
how a treasury limit is actually written down.

**Spec:** §6.4 — UTC calendar day.

### D-B6 · `clearance` mixes profile vocabularies

`clearance/src/lib/chp.ts` emits `PROVISIONAL_LOCK` (a Profile A deliberation state) from
a capital-gate context alongside `PROVISIONAL` and `LOCKED`. Profile B has no
`PROVISIONAL_LOCK`; there is no third-party validation step in a synchronous gate for it
to be waiting on.

**Spec:** §2 — a Profile B implementation MUST NOT emit `PROVISIONAL_LOCK`.

### D-A2 · Accuracy guard exists in only one Profile A port

`convergence/src/convergence/chp/accuracy.py` implements the CFO accuracy guard and the
"LOCKED but vulnerabilities open → downgrade" rule. The canonical port has no equivalent,
so the stronger guarantee applied only to decisions routed through `convergence`.

**Spec:** §5.8 — the guard is normative for Profile A.
**Vectors:** `A/guard/*`.

### D-A3 · Unbounded rounds in practice

`STATE_MACHINE.md` documents forcing `UNRESOLVED` at round 5, but no surveyed port
implements the bound; `next_round()` increments indefinitely. Nothing stops a session
looping past 5 rounds.

**Spec:** §5.6 — rounds MUST terminate; `force_unresolved()` in the reference.

---

## Remediation order

1. **D-B5** — an approval path that bypasses a policy check on capital movement. Fix first.
2. **D-A1** — finance decisions gated at 70 instead of 100.
3. **D-B1 / D-B3** — adopt canonical hashing; note this **changes historical hashes**, so
   record the cutover point in the ledger rather than rewriting old entries.
4. **D-B2 / D-B6** — normalise state vocabulary at the serialisation boundary.
5. **D-B4** — switch to the UTC calendar day.
6. **D-A2 / D-A3** — port the accuracy guard and the round bound into the canonical implementation.

Adopting §3.1 canonicalisation invalidates previously computed hashes by design. Do not
retro-hash old records: append a ledger entry marking the version change, and verify
pre-cutover entries with the old rule. Rewriting history to make a chain validate defeats
the purpose of chaining it.
