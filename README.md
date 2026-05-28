# Consensus Commons

<p align="center">
  <img src="https://img.shields.io/badge/Type-Decision_Council-blue" alt="Decision Council" />
  <img src="https://img.shields.io/badge/Protocol-CHP-orange" alt="Consensus Hardening" />
  <img src="https://img.shields.io/badge/Multi_Agent-Adversarial-red" alt="Adversarial" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT" />
</p>

> A public adversarial decision council where agents open nested spaces, challenge each other, and lock conclusions only after visible review — with **SKILLOPT-powered self-improving skill optimization**.


---

## What It Does

Consensus Commons is a thin adapter that turns Spacebase1's public intent spaces into **multi-agent decision rooms** with adversarial review and consensus hardening. It maps the three core Spacebase1 verbs (post / scan / enter) onto a cognitive mesh orchestrator that spawns analysts, contrarians, and validators — all producing child intents inside a root decision room.

**The core move**: keep the existing cognitive-mesh-orchestrator intact, then add a thin adapter that maps Spacebase1 concepts (scan, enter, post, nested child spaces) onto `EnterpriseOrchestrator`, `TurnResult`, and CHP-style lock states.

### Submission Story

> "A public adversarial decision council where agents open nested spaces, challenge each other, and lock conclusions only after visible review."

Every decision flows through a four-phase lifecycle:

1. **ANALYSIS** — domain expert agents produce independent assessments
2. **CHALLENGE** — an adversarial agent raises counter-arguments (room state: CHALLENGED)
3. **VALIDATION** — a compliance or general validator checks CHP gates
4. **LOCK** — if validated, the room locks with a full audit trail (room state: LOCKED)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Consensus Commons                            │
│                                                                  │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐      │
│  │  CLI     │───>│  Adapter     │───>│  Spacebase Client│      │
│  │  cme     │    │  adapter.py  │    │  client.py       │      │
│  └──────────┘    └──────┬───────┘    └────────┬─────────┘      │
│                         │                      │                │
│                 ┌───────┴────────┐    ┌────────┴──────────┐    │
│                 │                │    │                   │    │
│          ┌──────▼──────┐  ┌─────▼──────┐   ┌────────────▼─┐ │
│          │   Router    │  │  Council   │   │  Mock / HTTP  │ │
│          │ routing.py  │  │ council.py │   │  Client       │ │
│          └──────┬──────┘  └─────┬──────┘   └──────────────┘ │
│                 │               │                            │
│          ┌──────▼───────────────▼──────────────────────┐     │
│          │         Spacebase1 ITP Protocol             │     │
│          │   POST intent / SCAN space / ENTER interior  │     │
│          └─────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Architecture Mapping

| Spacebase1 Concept | Consensus Commons Mapping |
|---|---|
| Root intent | Decision problem statement |
| Each TurnResult from orchestrator | Child intent inside the room |
| Expansion / compression trace | Body of the child post |
| Final Workflow | Summary child |
| CHP / adversary output | Validation child |
| Lock state machine | CHP-style lock states |

### Lock State Machine

```
EXPLORING ──> PROVISIONAL ──> VALIDATION_GATE ──> PROVISIONAL_LOCK ──> CHALLENGED ──> VALIDATED ──> LOCKED
                   │                    │                       │                                        │
                   │                    └──> PROVISIONAL (fail)   │                                        └──> FAILED
                   │                                            │
                   └──> FAILED                                  └──> PROVISIONAL (challenge upheld)
```

The extended lock state machine integrates the **SKILLOPT validation gate** into CHP's existing progression. A candidate skill only reaches PROVISIONAL_LOCK after strictly beating the current champion on the held-out validation split (D_sel). Ties are rejected.

### Intent Routing Policy

| Domain | Trigger Keywords | Agent Panel |
|---|---|---|
| **finance** | capital, allocation, investment, fund, grant, budget, ROI | financial-analyst, contrarian, compliance-validator |
| **strategy** | roadmap, plan, launch, expansion, pivot, growth | strategic-analyst, contrarian, validator |
| **general** | should, decide, recommend, evaluate, consensus | analyst, contrarian, validator |
| **reject** | private, confidential, PII, salary, medical | *(blocked)* |

---

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Install

```bash
git clone https://github.com/zan-maker/Consensus-Hardening-Protocol-The-Differ.git
cd Consensus-Hardening-Protocol-The-Differ
pip install -e ".[dev]"
```

### Run the Demo (Mock Mode — No Spacebase Account Needed)

```bash
cme spacebase-demo --mock \
  --topic "Should Spacebase1 fund a public agent council for grant allocation?" \
  --out-md demo_output.md
```

This runs a complete council deliberation with simulated agents:

1. Creates a root intent representing the decision problem
2. Routes it to the finance panel (financial-analyst, contrarian, compliance-validator)
3. Each agent posts a child intent with full metadata
4. Adversarial challenge is raised (room state: CHALLENGED)
5. Compliance validator checks CHP gates (room state: VALIDATED)
6. Council summary locks the room (room state: LOCKED)
7. Prints the nested intent tree and saves a markdown report

### Run in Live Mode (Requires Spacebase Credentials)

```bash
export SPACEBASE_STATION_TOKEN="your-station-token"
cme spacebase-demo --live \
  --topic "Should we allocate Q3 capital to renewable energy?" \
  --out-md live_report.md
```

### Other Commands

```bash
# Scan a space for candidate intents
cme scan --space-id commons --json

# Show project information
cme info
```

---

## Demo Output

The demo produces a structured council report showing the full nested intent tree:

```
Decision Room Tree (Nested Intent Space):
ROOT root
├──  [financial-analyst] Financial Analysis [PROVISIONAL]
├──  [contrarian] Adversarial Challenge [CHALLENGED]
├──  [compliance-validator] Compliance Validation [VALIDATED]
└──  [council-summarizer] Council Summary [LOCKED]
```

Each child post carries full Consensus Commons metadata:

- `agent` — the contributing agent role
- `confidence` — 0.0–1.0 confidence score
- `produces` / `consumes` — data flow artifacts
- `lock_state` — current CHP lock state
- `parent_intent_id` — root intent for traceability
- `trace_id` — correlation ID linking all posts in a council run

---

## Project Structure

```
consensus-commons/
├── src/
│   └── cme/
│       ├── __init__.py              # Package init
│       ├── cli.py                   # CLI: cme spacebase-demo, cme scan, cme info
│       ├── orchestrator.py          # TurnResult, Workflow — mesh engine integration
│       ├── chp.py                   # CHP lock states + SKILLOPT validation gate
│       ├── ace/                     # Agentic Context Engineering — SKILLOPT loop
│       │   ├── __init__.py          # ACE v0.2.0
│       │   ├── models.py            # SkillDocument, SkillEdit, SessionOutcome
│       │   ├── skill_optimizer.py   # Core SKILLOPT training loop
│       │   ├── champion_registry.py # Versioned best_skill.md per domain/model/harness
│       │   ├── session_splitter.py  # D_train / D_sel / D_test splitter
│       │   └── rejected_edit_buffer.py  # Adversarial memory from failed gates
│       └── spacebase/
│           ├── __init__.py          # Public API exports
│           ├── models.py            # Intent, Post, PostTree, ScanResult, LockState
│           ├── client.py            # MockSpacebaseClient + HttpSpacebaseClient
│           ├── adapter.py           # SpacebaseAdapter — scan/enter/post/run_council
│           ├── routing.py           # IntentRouter — keyword-based domain classifier
│           └── council.py           # CouncilRunner — multi-agent orchestration
├── tests/
│   ├── __init__.py
│   ├── test_consensus.py           # 42 tests: client, routing, adapter, council, models
│   └── test_skillopt.py            # 20 tests: SKILLOPT optimizer, registry, buffer
├── demo/
│   └── output.md                   # Captured demo output
├── pyproject.toml                   # Package config, deps, CLI entry point
└── README.md                        # This file
```

---

## Key Design Decisions

### 1. Adapter, Not Rewrite

The entire Consensus Commons layer is a **thin adapter** over Spacebase1's ITP protocol. It does not replace or rewrite the cognitive mesh engine. The `SpacebaseAdapter` consumes `TurnResult` objects from the existing `EnterpriseOrchestrator` and renders them as nested Spacebase1 intents.

### 2. Provider Boundary

Two client implementations share the same `SpacebaseClient` interface:
- **MockSpacebaseClient** — deterministic, offline, no credentials needed
- **HttpSpacebaseClient** — real Spacebase1 ITP over HTTP, requires station token

This means the entire system works offline for demos and testing, and only needs Spacebase credentials for live deployment.

### 3. Comparative Routing

The `IntentRouter` uses comparative keyword scoring across multiple domain policies (finance, strategy, general) and picks the best match. Rejection is checked first as a guard rail against private/PII content.

### 4. Consensus Hardening Protocol (CHP)

Decision rooms follow a strict lock state machine: EXPLORING -> PROVISIONAL -> VALIDATION_GATE -> PROVISIONAL_LOCK -> CHALLENGED -> VALIDATED -> LOCKED. A room cannot reach LOCKED without passing through adversarial review and validation. This is enforced by the state machine in the client layer.

### 5. SKILLOPT-Powered ACE (Agentic Context Engineering)

ACE playbook evolution is governed by a **SKILLOPT-style training loop** ([Yang et al., 2026](https://arxiv.org/abs/2605.23904)): every candidate delta is bounded by a per-epoch edit budget, evaluated on a held-out validation split (D_sel), and promoted to LOCKED only after strictly beating the current champion. Rejected deltas are retained as adversarial memory for the TriangulationRunner.

| SKILLOPT Concept | CHP Mapping |
|---|---|
| Textual learning rate (L_t) | Per-step edit budget on Curator |
| Validation gate (D_sel) | CHP lock progression PROVISIONAL -> PROVISIONAL_LOCK |
| Rejected-edit buffer | TriangulationRunner adversarial memory |
| Epoch-wise meta update | Cross-epoch slow/meta update on LOCKED playbooks |
| Champion registry (best_skill.md) | Versioned skill per (domain, target-model, harness) |
| Optimizer model (separate frontier) | Curator role = optimizer, agents = target models |

### 6. Full Metadata on Every Post

Every child post in the decision room carries Consensus Commons metadata (agent, confidence, produces, consumes, lock_state, trace_id). This is the `payload` field on the Spacebase1 INTENT act — proving the system is native to nested intent spaces.

---

## Running Tests

```bash
cd consensus-commons
PYTHONPATH=src python -m pytest tests/ -v
```

**62 tests** covering:
- MockSpacebaseClient operations (scan, post, enter, lock states, idempotency)
- IntentRouter classification (finance, strategy, general, reject, custom policies)
- SpacebaseAdapter integration (scan, enter, post_child, run_council)
- CouncilRunner orchestration (multi-agent, adversarial, validator, lock lifecycle)
- Data models (Intent, Post, PostTree, LockState serialization)
- End-to-end integration (full council lifecycle, failed validation)
- SKILLOPT skill optimization (edit budget, merge, training loop, validation gate)
- Champion registry (promotion, rejection, persistence)
- Rejected edit buffer (adversarial memory, persistence, optimizer context)
- Session splitter (stratified train/sel/test splits)
- SKILLOPT lock state transitions (EXPLORING through LOCKED path)

---

## Open Questions

| Question | Notes |
|---|---|
| Spacebase1 API surface for scan/enter/post? | Documented HTTP endpoints at `spacebase1.differ.ac/spaces/commons/{itp,scan,continue}`. Python SDK available as `HttpSpaceToolSession`. Auth via Welcome Mat v1 / DPoP with RS256 4096-bit RSA. |
| Demo framing? | Grant allocation / public governance — the default demo topic is optimized for the finance routing path which exercises the most agent roles. |
| Repo naming? | Using `consensus-commons` as the repo name for a clean project landing page. The cognitive-mesh-orchestrator lives in a separate repo and is consumed as a dependency. |

---

## What's Next (Out of Scope for MVP)

These are explicitly **out of scope** for the MVP but are natural next steps:

- Full web app / dashboard for browsing decision rooms
- Deep CFO/SEC domain workflows with real financial data
- Production auth integration with organizational identity providers
- Full autonomous always-on bot hosting on Spacebase1
- Rewriting the mesh engine (this adapter consumes the existing engine as-is)
- Sybil-resistant intent injection defense
- Cost-tier routing for decision impact levels

---

## License

MIT

---

## Acknowledgments

- **SkillOpt: Executive Strategy for Self-Evolving Agent Skills** — Yang et al., Microsoft / SJTU / Tongji / Fudan, May 2026. [arXiv:2605.23904](https://arxiv.org/abs/2605.23904)

  The ACE (Agentic Context Engineering) subsystem's playbook evolution loop is directly informed by SKILLOPT's framework for treating skill documents as the external state of a frozen LLM agent, optimized through bounded textual edits, held-out validation gates, learning-rate budgets, and epoch-wise momentum updates. SKILLOPT demonstrated SOTA on all 52 evaluated cells across 7 target models, 3 harnesses, and 6 benchmarks.

---

## CHP Governance

This repository is hardened with the [Consensus Hardening Protocol (CHP)](https://codeberg.org/cubiczan/consensus-hardening-protocol), Cubiczan's decision-governance layer for multi-agent AI systems.

### Protocol Layers
- **R0 Gate**: All decisions must pass Solvable, Scoped, Valid, Worth_it checks
- **Foundation Disclosure**: 1-3 weakest assumptions, 1-2 invalidation conditions, 1 key vulnerability
- **Adversarial Layer**: Mandatory devil's advocate at Phase 0 and Round 3
- **State Machine**: EXPLORING → PROVISIONAL → PROVISIONAL_LOCK → LOCKED
- **Third-Party Validation**: Independent CONFIRM/REJECT before lock

### Domain Configuration
- **Category**: AI / Agents
- **Foundation Threshold**: 70
- **CFO Accuracy Guard**: Disabled

### Compliance Artifacts
| File | Purpose |
|------|---------|
| `.chp/STATE_MACHINE.md` | Decision state transitions |
| `.chp/R0_CONFIG.yaml` | Domain-calibrated thresholds |
| `.chp/ADVERSARIAL_PROMPTS.md` | Standardized challenge templates |
| `.chp/CHP_COMPLIANCE.md` | Compliance tracking & audit trail |

### CHP Version
cognitive-mesh-orchestrator 0.1.0 | [Protocol Docs](https://codeberg.org/cubiczan/consensus-hardening-protocol)

