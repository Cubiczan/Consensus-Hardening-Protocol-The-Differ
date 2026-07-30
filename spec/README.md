# CHP Specification

The normative definition of the Consensus Hardening Protocol, plus a conformance suite any
implementation can be tested against.

```
spec/
├── CHP-v1.0.md                     the spec (normative)
├── DIVERGENCES.md                  what the shipped ports get wrong, with severities
├── golden-vectors/                 expected values, generated — never hand-edited
│   ├── canonicalization.json
│   ├── audit-ledger.json
│   ├── profile-a-deliberation.json
│   └── profile-b-capital-gate.json
└── conformance/
    ├── chp_reference.py            reference implementation (the tie-breaker)
    ├── generate_vectors.py         regenerates golden-vectors/
    ├── run_conformance.py          the runner
    └── adapters/
        └── legacy_divergence_adapter.py   fixture that MUST fail
```

## Start here

CHP names **two different protocols** that share a state vocabulary. Read
[§2](CHP-v1.0.md#2-two-profiles) first and work out which one you have:

- **Profile A — Deliberation.** Multi-round adversarial hardening of a *judgement*.
  R0 gate, foundation disclosure/attack, domain score floors, phases, third-party lock.
- **Profile B — Capital Gate.** Synchronous policy gate on one *action* that moves money.
  Notional caps, daily budget, HITL threshold, provenance record.

## Test an implementation

```bash
# the reference must always pass
python3 spec/conformance/run_conformance.py --adapter reference

# your port, any language, via the line-JSON adapter protocol (§7.2)
python3 spec/conformance/run_conformance.py --adapter-cmd "node path/to/adapter.js"

# only the profile you implement
python3 spec/conformance/run_conformance.py --adapter-cmd "..." --profile B
```

Exit code is `0` only on full conformance. Unsupported ops report SKIP rather than FAIL,
so a Profile-B-only gate is not penalised for lacking deliberation ops.

## Confirm the suite still bites

A suite that only ever passes is decoration. This fixture reproduces the real divergences
found in shipped ports and **must fail**:

```bash
python3 spec/conformance/run_conformance.py \
  --adapter-cmd "python3 spec/conformance/adapters/legacy_divergence_adapter.py"
# expect: FAILED (34 failures), exit 1
```

## Writing an adapter

Read one JSON request per line on stdin, write one response per line on stdout:

```js
// adapter.js
const readline = require('readline');
const chp = require('../src/chp');

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  if (!line.trim()) return;
  const { op, args } = JSON.parse(line);
  try {
    let result;
    switch (op) {
      case 'content_hash':  result = chp.contentHash(args.payload); break;
      case 'evaluate_gate': result = chp.evaluate(args.action, args.policy, args.committed_today); break;
      default: process.stdout.write(JSON.stringify({ ok: false, error: 'unsupported op' }) + '\n'); return;
    }
    process.stdout.write(JSON.stringify({ ok: true, result }) + '\n');
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e) }) + '\n');
  }
});
```

Return objects may carry extra keys — your own `decision_id`, timestamps, logging fields —
without failing conformance. Every field the spec names must match.

## Changing the spec

1. Edit `conformance/chp_reference.py` — it is the tie-breaker, so behaviour changes start there.
2. `python3 conformance/generate_vectors.py`
3. Review the vector diff. A large diff means you changed more than you intended.
4. Update `CHP-v1.0.md` and bump per [§8](CHP-v1.0.md#8-versioning).

Never hand-edit a golden vector. If a vector looks wrong, the reference is wrong.
