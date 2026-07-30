# Consensus Hardening Protocol (CHP) — Specification v1.0

**Status:** Normative · **Version:** 1.0 · **Date:** 2026-07-30

CHP is a protocol for hardening decisions made with or by AI agents. It exists because
an agent that is confidently wrong is more dangerous than one that is uncertain, and
because a decision nobody can audit afterwards is indistinguishable from a guess.

This document is normative. The tie-breaker for any ambiguity is
[`conformance/chp_reference.py`](conformance/chp_reference.py); where a port disagrees
with the reference, the port is wrong or this spec needs an errata.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be
interpreted as in RFC 2119.

---

## 1. Why this document exists

At the time of writing, 30 repositories in this portfolio reference "CHP". They do not
all mean the same thing, and the ones that do mean the same thing do not agree on the
details. Concretely, before this spec existed:

- Two capital gates hashed their audit records differently, so the same logical decision
  produced different content hashes in each — making cross-system verification impossible.
- One gate emitted `"locked"` and another `"LOCKED"` for the same state.
- The documented foundation-score floor for finance decisions (100) was **never enforced**;
  every domain was gated at 70.
- One gate's human-approval path skipped the confidence check, so a human could approve
  an action the gate itself would have blocked.

None of these were visible from any single repository. All four are now conformance
failures. See [DIVERGENCES.md](DIVERGENCES.md).

---

## 2. Two profiles

"CHP" names two related but distinct protocols. Conflating them is the single largest
source of confusion in the portfolio. An implementation **MUST** declare which profile
it implements; it **MAY** implement both.

### Profile A — Deliberation

A multi-round adversarial procedure for hardening a *reasoning* process. Applies when a
human or agent is reaching a consequential judgement: an architecture decision, a capital
allocation, a board recommendation. Its output is a **dossier** with a documented
foundation, an adversarial challenge, and a lock state.

Concern: *is this conclusion actually sound, or does it just sound sound?*

### Profile B — Capital Gate

A synchronous runtime gate on a *single proposed action* that moves money. Applies at the
moment before execution: a trade, a transfer, a payment. Its output is an allow/deny plus
an auditable provenance record.

Concern: *is this specific action within policy, and who approved it?*

| | Profile A | Profile B |
|---|---|---|
| Timescale | Minutes to days, multi-round | Milliseconds, single call |
| Subject | A judgement | An action |
| Adversary | Another model or person | A deterministic rule set |
| Terminal states | `LOCKED`, `CONVERGED`, `UNRESOLVED`, `REFRAME_REQUIRED`, `HALT` | `LOCKED`, `BLOCKED`, `HITL_REQUIRED` |
| Output | Dossier + lock | Decision + provenance record |

They share the `EXPLORING → PROVISIONAL → LOCKED` vocabulary and the audit-ledger
format (§3.3). Everything else differs. A Profile B implementation **MUST NOT** emit
`PROVISIONAL_LOCK`, `CONVERGED`, `UNRESOLVED`, or `REFRAME_REQUIRED`; a Profile A
implementation **MUST NOT** emit `BLOCKED` or `HITL_REQUIRED`.

> `clearance/src/lib/chp.ts` currently emits `PROVISIONAL_LOCK` from a capital-gate
> context, mixing the two vocabularies. See D-B6.

---

## 3. Canonical serialisation and hashing

Every auditable CHP artefact is hashed. For two implementations to verify each other,
they must agree on the bytes being hashed — so canonicalisation is normative.

### 3.1 Canonical JSON

An implementation **MUST** serialise a hashed payload as JSON with:

- object keys sorted lexicographically by UTF-16 code unit, **recursively**;
- no insignificant whitespace (`,` and `:` separators, no spaces);
- UTF-8 output with characters emitted literally, **not** `\uXXXX`-escaped;
- `NaN`, `Infinity`, and `-Infinity` rejected as an error, never serialised;
- array order preserved exactly (arrays are ordered data, not sets).

```
{"a":2,"b":1}                       ← canonical
{"b":1,"a":2}                       ← NOT canonical (unsorted)
{"note":"café"}                ← NOT canonical (escaped non-ASCII)
{"a": 2, "b": 1}                    ← NOT canonical (whitespace)
```

`{"b":1,"a":2}` and `{"a":2,"b":1}` describe the same object and **MUST** hash
identically. Golden vectors: [`golden-vectors/canonicalization.json`](golden-vectors/canonicalization.json).

### 3.2 Content hash

`content_hash(payload) = hex(SHA-256(utf8(canonical_json(payload))))`

Lowercase hex, 64 characters.

### 3.3 Signed audit ledger

A CHP audit ledger is an append-only sequence of entries, each signed over the previous
signature. This is the shared substrate under both profiles.

```
sig[0] = content_hash({"prev_sig": "",        "entry": entry[0]})
sig[n] = content_hash({"prev_sig": sig[n-1], "entry": entry[n]})
```

- The first entry's `prev_sig` **MUST** be the empty string.
- A verifier **MUST** recompute the entire chain from `prev_sig = ""`.
- Entries **MUST NOT** be edited or removed. Chaining makes any such change invalidate
  every subsequent signature, which is the entire point.
- The hashed payload **MUST NOT** include the entry's own signature.

Implementations **MAY** additionally HMAC each entry with a shared secret for
authenticity. Authenticity and integrity are separate properties: the hash chain gives
tamper-evidence, HMAC gives origin proof. Signing with HMAC does not remove the
requirement to chain.

---

## 4. Shared state vocabulary

### 4.1 Wire form

State values **MUST** be UPPERCASE on the wire and in hashed payloads:

`EXPLORING`, `PROVISIONAL`, `PROVISIONAL_LOCK`, `LOCKED`, `CONVERGED`, `UNRESOLVED`,
`REFRAME_REQUIRED`, `REQUIRES_HUMAN_VERIFICATION`, `HITL_REQUIRED`, `BLOCKED`, `HALT`.

An implementation **MAY** use any internal representation, but **MUST** serialise
uppercase. Comparison of a received state **SHOULD** be case-sensitive, so that a
lowercase value is a loud failure rather than a silent one.

*Rationale: uppercase is what four of five surveyed implementations already emit, and
matches the enum values in the canonical Python port.*

### 4.2 Fail-closed

Wherever this spec allows a choice between refusing and proceeding, an implementation
**MUST** refuse. Specifically:

- A missing, unreadable, or malformed policy file **MUST** fall back to the conservative
  defaults in §6.2 — never to unlimited.
- An unknown domain **MUST** use the default foundation floor (§5.3), not 0.
- An unparseable payload envelope **MUST** be rejected, not best-effort repaired.
- An error inside a gate **MUST** be treated as a denial.

---

## 5. Profile A — Deliberation

### 5.1 Session shape

A session concerns one `DecisionCase`, progressing through phases in bounded rounds:

```
FOUNDATION (phase 0) → SPEC (phase 1) → IMPLEMENTATION (phase 2)
```

### 5.2 R0 gate (session entry)

Before any deliberation, four checks run. All four **MUST** pass or the session **MUST**
enter `HALT`.

| Check | Question |
|---|---|
| `Solvable` | Can this be resolved within the domain's constraints at all? |
| `Scoped` | Are the scope boundaries written down? |
| `Valid` | Are both current state and goal state specified? |
| `Worth_it` | Do the stakes justify the governance overhead? |

Each check reports `PASS` or `FATAL`. The gate verdict is `PASS` only if all four are
`PASS`, otherwise `HALT`.

*`Worth_it` is not ceremony. CHP is expensive; applying it to a decision that does not
warrant it trains people to route around it.*

### 5.3 Foundation disclosure, attack, and score

The proposer **MUST** first disclose its own weakest points:

- `weakest_assumptions`: 1–3 items (**MUST** be non-empty, **MUST NOT** exceed 3)
- `invalidation_conditions`: 1–2 items
- `key_vulnerability`: required, non-empty

An adversary then attacks that disclosure, producing `assumption_attacks` (**MUST**
address each disclosed assumption, up to 3), a `vulnerability_strike`, and a
`foundation_score` in `[0, 100]`.

The score is gated against a **domain-dependent floor**:

| Domain | Floor | Why |
|---|---|---|
| `general`, `ai`, `agents` | 70 | Default |
| `blockchain`, `defi` | 85 | On-chain actions are irreversible |
| `finance`, `cfo`, `capital_allocation`, `board_decision` | 100 | A wrong number restates audited accounts |
| *unlisted* | 70 | Fail to the default, never to 0 |

`foundation_score >= floor(domain)` yields `PASS`; below yields `REFRAME`, and the
session enters `REFRAME_REQUIRED`.

> The canonical port hardcoded 70 for every domain, so a finance decision scoring 70
> passed a gate documented as requiring 100. This is D-A1, the highest-severity finding
> in the survey.

### 5.4 Phase gate

Entering `IMPLEMENTATION` requires the spec phase to be locked. For `round_number >= 3`,
the phase gate passes only if phase-1 state is `PROVISIONAL_LOCK`, `LOCKED`, or
`CONVERGED`; otherwise `PHASE_GATE_FAIL`. Rounds 0–2 always pass.

### 5.5 Round progression

```
(FOUNDATION, any) → (SPEC, 1)
(SPEC, r >= 2)    → (IMPLEMENTATION, 3)
otherwise         → (same phase, r + 1)
```

### 5.6 Bounded rounds

Deliberation **MUST** terminate. At `round_number >= 5` without convergence, the session
**MUST** be forced to `UNRESOLVED`. `UNRESOLVED` is a valid, reportable outcome — an
honest "we did not converge" beats a manufactured consensus.

### 5.7 Model parity

An adversarial round is only meaningful if the adversary can actually push back. Parity
compares model tiers (`small` < `mid` < `high` < `frontier`):

| Tier gap | Delta | Meaning |
|---|---|---|
| 0 | `NONE` | Comparable weight |
| 1 | `MINOR` | Watch for dominance bias |
| ≥ 2 | `SIGNIFICANT` | Challenge is not credible |
| either unknown | `MINOR` | Advisory only |

A `SIGNIFICANT` delta **SHOULD** be surfaced in the dossier. An implementation
**SHOULD NOT** treat an adversarial round from a materially weaker adversary as
satisfying §5.3.

### 5.8 Accuracy guard

Before a clean lock, a guard runs. It **MUST** return a failure requiring
`REQUIRES_HUMAN_VERIFICATION` when any of:

- `foundation_score < floor(domain)`;
- any `structural_vulnerabilities` remain open;
- any `blind_spots` remain unresolved.

A case already in `LOCKED` with open vulnerabilities **MUST** be downgraded rather than
trusted. *A lock is a claim that the work was done, not a way to stop asking.*

### 5.9 Payload envelope

Cross-system packets are wrapped so truncation is detectable:

```
BEGIN_PAYLOAD [<route>] [<payload_id>]
<body>
END_PAYLOAD [<route>] [<payload_id>]
```

A packet is valid only if the header and footer bracket-groups match exactly. The
receiver confirms with the literal string `[<route>] [<payload_id>] CONFIRMED`.
A mismatched or missing echo **MUST NOT** be treated as confirmed.

`payload_id` **SHOULD** be at least 6 characters from an unambiguous alphabet
(`A–Z`, `0–9`). It is a truncation detector, not a security token.

### 5.10 Third-party validation

`PROVISIONAL_LOCK` advances to `LOCKED` only on an external `CONFIRM`.

- `CONFIRM` → `LOCKED`, and the validated item is appended to `locked_decisions`.
- `REJECT` → back to `EXPLORING`, and `flip_criteria` **MUST** record what would change
  the verdict.

The validator **MUST NOT** be the proposer.

---

## 6. Profile B — Capital Gate

### 6.1 Contract

```
evaluate(action, policy, committed_today) -> decision
```

Synchronous, side-effect-free, deterministic. Given identical inputs it **MUST** return
an identical `content_hash`. It **MUST NOT** consult wall-clock time inside the hashed
payload, or two runs of the same decision will not agree.

### 6.2 Policy and conservative defaults

| Field | Default | Meaning |
|---|---|---|
| `max_notional` | `500.0` | Per-action ceiling |
| `daily_cap` | `2500.0` | Rolling UTC-day ceiling |
| `hitl_threshold` | `250.0` | At or above this, a human must approve |
| `min_confidence` | `0.55` | Signal-confidence floor |
| `allowed_actions` | *empty* | Empty means "do not check", not "allow all" |
| `per_asset_limits` | `{}` | Overrides `max_notional` per asset |

A missing or malformed policy **MUST** produce these defaults and **SHOULD** log at
warning level. It **MUST NOT** raise, and **MUST NOT** default to unlimited.

### 6.3 Evaluation order (normative)

1. **Sanity.** `notional` **MUST** be finite and `> 0`. A `NaN` notional makes every
   subsequent comparison meaningless, so this runs first.
2. **Hard rules**, all collected (not short-circuited, so the record lists every reason):
   allowed action, per-asset cap, max notional, projected daily cap, min confidence.
   Confidence is checked only when supplied.
3. **Any hard failure → `BLOCKED`.** `allowed = false`, `requires_human = false`.
4. **Only a fully clean action** reaches the threshold test:
   `notional >= hitl_threshold` → `HITL_REQUIRED` (`allowed = false`,
   `requires_human = true`); otherwise → `LOCKED` (`allowed = true`).

Ordering is normative. An implementation that tests the HITL threshold *before* the hard
rules will route an over-cap action to a human, inviting approval of something policy
forbids. **A policy violation is not a permission question.**

The threshold comparison is inclusive (`>=`): `notional == hitl_threshold` requires a
human.

### 6.4 Daily-cap window

The window **MUST** be the **UTC calendar day** (`YYYY-MM-DD`).

A rolling window anchored to process start is **NOT** conformant: the budget then depends
on restart time, so an identical action sequence passes on one host and is blocked on
another, and no auditor can reproduce either. See D-B4.

Only a `LOCKED` decision consumes budget. `BLOCKED` and `HITL_REQUIRED` contribute `0`
(`committed_delta`), so an action awaiting approval does not reserve budget it may never use.

### 6.5 Human approval

```
approve_human(action, policy, approver, committed_today) -> decision
```

**MUST** re-run the full §6.3 evaluation. A human approval is permission to cross the
HITL threshold — **not** permission to violate policy. An approved action that fails any
hard rule **MUST** be `BLOCKED`.

`approver` **MUST** be recorded in the provenance record.

> The legacy path re-checked only the notional caps, so a human could approve a
> low-confidence action that `evaluate()` had blocked. See D-B5.

### 6.6 Provenance record

Every decision — including denials — **MUST** emit a record containing at least: the
action, resulting state, `allowed`, `requires_human`, the per-rule claims with pass/fail,
and a `content_hash` over the normative field set:

```json
{"chp_version":"1.0","profile":"B","action":…,"asset":…,"notional":…,
 "confidence":…,"state":…,"allowed":…,"requires_human":…,"failed_rules":[…]}
```

`failed_rules` is sorted. `decision_id` and `timestamp` are recorded **alongside** the
hash, never inside it — including them would make the hash unreproducible and defeat
cross-implementation verification. Records **SHOULD** be appended to a §3.3 ledger.

---

## 7. Conformance

An implementation is **CHP v1.0 conformant** for a profile when it passes every golden
vector for §3 plus that profile's vectors, with no failures.

### 7.1 Running the suite

```bash
python3 spec/conformance/run_conformance.py --adapter reference
python3 spec/conformance/run_conformance.py --adapter-cmd "node adapters/my-port.js" --profile B
```

Exit code is `0` only on full conformance, so this drops directly into CI.

### 7.2 Adapter protocol

An adapter is any executable reading one JSON request per line on stdin and writing one
JSON response per line on stdout, in order:

```
-> {"op":"content_hash","args":{"payload":{"a":2,"b":1}}}
<- {"ok":true,"result":"d3626ac3…"}
<- {"ok":false,"error":"unsupported op"}
```

Ops: `canonical_json`, `content_hash`, `chain_hash`, `r0_gate`, `foundation_floor`,
`foundation_verdict`, `phase_gate`, `next_round`, `model_parity`, `accuracy_guard`,
`validate_payload_envelope`, `payload_echo_confirmed`, `evaluate_gate`, `approve_human`.

`{"ok":false,"error":"unsupported op"}` reports **SKIP**, not **FAIL** — a Profile-B-only
gate is not penalised for lacking deliberation ops. Comparison allows extra keys in
returned objects, so an implementation may carry its own metadata, but every field this
spec names must match.

### 7.3 Regenerating vectors

```bash
python3 spec/conformance/generate_vectors.py
```

Every expected value is computed by the reference implementation; none are hand-written.
Re-run after any intentional reference change and review the diff — a large diff means
you changed more than you meant to.

### 7.4 Verifying the suite still bites

```bash
python3 spec/conformance/run_conformance.py \
  --adapter-cmd "python3 spec/conformance/adapters/legacy_divergence_adapter.py"
```

This fixture reproduces the real divergences found in shipped ports and **MUST** fail
(34 failures at time of writing). If it ever passes, the suite has stopped detecting
regressions.

---

## 8. Versioning

Semantic, on the protocol:

- **Patch** — clarification, no behaviour change; vector hashes unchanged.
- **Minor** — new optional capability; existing conformant implementations stay conformant.
- **Major** — any change to canonicalisation, the hashed field set, state semantics, or
  evaluation order. Vector hashes change; all implementations must be revalidated.

Hashed payloads carry `chp_version`. An implementation receiving an unrecognised major
version **MUST** refuse to verify rather than assume compatibility.

---

## Appendix A — Implementation checklist

- [ ] Declares profile(s) (§2)
- [ ] Canonical JSON: recursive key sort, no whitespace, literal UTF-8 (§3.1)
- [ ] SHA-256 over canonical JSON, lowercase hex (§3.2)
- [ ] Ledger chains `prev_sig`, first is `""` (§3.3)
- [ ] States serialised UPPERCASE (§4.1)
- [ ] Malformed policy → conservative defaults, never unlimited (§4.2, §6.2)
- [ ] **A:** foundation floor is domain-aware (§5.3)
- [ ] **A:** rounds bounded, forced `UNRESOLVED` at 5 (§5.6)
- [ ] **A:** accuracy guard downgrades a dirty lock (§5.8)
- [ ] **A:** validator is not the proposer (§5.10)
- [ ] **B:** hard rules evaluated before the HITL threshold (§6.3)
- [ ] **B:** HITL comparison inclusive (§6.3)
- [ ] **B:** daily window is the UTC calendar day (§6.4)
- [ ] **B:** `approve_human` re-runs the full evaluation (§6.5)
- [ ] **B:** `timestamp`/`decision_id` excluded from the hash (§6.6)
- [ ] Conformance suite green in CI (§7.1)
