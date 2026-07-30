# Consensus Commons

<p align="center">
  <img src="https://img.shields.io/badge/Type-Decision_Council-blue" alt="Decision Council" />
  <img src="https://img.shields.io/badge/Protocol-CHP-orange" alt="Consensus Hardening" />
  <img src="https://img.shields.io/badge/Multi_Agent-Adversarial-red" alt="Adversarial" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT" />
</p>

> A public adversarial decision council where agents open nested spaces, challenge each other, and lock conclusions only after visible review — with **SKILLOPT-powered self-improving skill optimization**.

---

## 📐 CHP is specified here

This repository holds the **normative specification** for the Consensus Hardening Protocol,
which 30+ repositories across the portfolio depend on.

| | |
|---|---|
| **[spec/CHP-v1.0.md](spec/CHP-v1.0.md)** | The specification. Start at §2 — "CHP" names *two* protocols. |
| **[spec/DIVERGENCES.md](spec/DIVERGENCES.md)** | What the shipped ports get wrong, by severity. |
| **[spec/conformance/](spec/conformance/)** | Reference implementation + conformance runner. |

If you are implementing or porting CHP, test it:

```bash
python3 spec/conformance/run_conformance.py --adapter-cmd "your-adapter" --profile B
```

Any language works — the [adapter protocol](spec/CHP-v1.0.md#72-adapter-protocol) is one
JSON object per line over stdio. Exit code is `0` only on full conformance.

---

## What It Does

Consensus Commons is a thin adapter that turns Spacebase1's public intent spaces into **multi-agent decision rooms** with adversarial review and consensus hardening. It maps the three core Spacebase1 verbs (post / scan / enter) onto a cognitive mesh orchestrator that spawns analysts, contrarians, and validators — all producing child intents inside a root decision room.

**The core move**: keep the existing cognitive-mesh-orchestrator intact, then add a thin adapter that maps Spacebase1 concepts (scan, enter, post, nested child spaces) onto `EnterpriseOrchestrator`, `TurnResult`, and CHP-style lock states.

### Submission Story

> "A public adversarial decision council where agents open nested spaces, challenge each other, and lock conclusions only after visible review."

Every decision flows through a six-phase lifecycle:

1. **R0 GATE** — intent is checked for Solvability, Scope, Validity, and Worth before entering the council
2. **ANALYSIS** — domain expert agents produce independent assessments
3. **CHALLENGE** — an adversarial agent raises counter-arguments (room state: CHALLENGED)
4. **VALIDATION** — a compliance or general validator checks CHP gates
5. **LOCK** — if validated, the room locks with a full audit trail (room state: LOCKED)
6. **QUALITY GATE + LEARNING** — the council output is evaluated through 7 quality dimensions, a foundation disclosure is generated, and learning candidates are proposed for the next cycle

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Consensus Commons                               │
│                                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐            │
│  │  CLI     │───>│  Adapter     │───>│  Spacebase Client│            │
│  │  cme     │    │  adapter.py  │    │  client.py       │            │
│  └──────────┘    └──────┬───────┘    └────────┬─────────┘            │
│                         │                      │                      │
│                 ┌───────┴────────┐    ┌────────┴──────────┐          │
│                 │                │    │                   │          │
│          ┌──────▼──────┐  ┌─────▼──────┐   ┌────────────▼─┐       │
│          │   Router    │  │  Council   │   │  Mock / HTTP  │       │
│          │ routing.py  │  │ council.py │   │  Client       │       │
│          └──────┬──────┘  └─────┬──────┘   └──────────────┘       │
│                 │               │                                    │
│          ┌──────▼──────┐  ┌────▼───────────┐                        │
│          │   R0 Gate   │  │ Quality Gate   │                        │
│          │  r0_gate.py │  │ council_qual.. │                        │
│          └─────────────┘  └────┬───────────┘                        │
│                               │                                     │
│          ┌──────────────┬──────┴──────┐                             │
│          │              │              │                             │
│   ┌──────▼────────┐  ┌─▼──────────┐  ┌▼────────────────┐          │
│   │ Foundation     │  │  Learning  │  │ Spacebase1 ITP  │          │
│   │ Disclosure      │  │  Loop      │  │ Protocol        │          │
│   │ foundation_..py │  │ council_.. │  │                  │          │
│   └────────────────┘  └────────────┘  └─────────────────┘          │
└──────────────────────────────────────────────────────────────────────────┘
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
│       ├── __init__.py              # Package init (v0.3.0)
│       ├── cli.py                   # CLI: cme spacebase-demo, cme scan, cme info
│       ├── orchestrator.py          # TurnResult, Workflow — mesh engine integration
│       ├── chp_locks.py             # CHP lock states + SKILLOPT validation gate mapping
│       ├── agent.py                 # MeshAgent base class with protocol integration
│       ├── protocol.py              # Cognitive Mesh Protocol — expansion/compression reasoning
│       ├── context.py               # ContextEngine — in-memory organizational knowledge store
│       ├── r0_gate.py               # R0 first-gate evaluation (Solvable/Scoped/Valid/Worth It)
│       ├── council_quality_gate.py  # 7-dimension council quality evaluation
│       ├── council_learning.py      # Self-improving learning loop for councils
│       ├── foundation_disclosure.py # Weakest assumption disclosure module
│       ├── chp/                     # Canonical CHP core primitives
│       │   ├── __init__.py          # Package exports
│       │   ├── models.py            # DecisionCase, Dossier, FoundationDisclosure, etc.
│       │   ├── gates.py             # R0 gate + phase gate evaluation
│       │   ├── payloads.py          # Payload envelope integrity (build/validate/extract)
│       │   ├── orchestrator.py      # CHPOrchestrator — full session lifecycle
│       │   ├── registry.py          # DecisionRegistry with JSON persistence
│       │   ├── validators.py        # Third-party validation for lock progression
│       │   ├── rounds.py            # Round progression (FOUNDATION → SPEC → IMPLEMENTATION)
│       │   ├── foundation.py        # Foundation verdicts + disclosure/attack validation
│       │   ├── devil.py             # Devil's advocate helpers
│       │   └── parity.py            # Model parity assessment with tier inference
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
│   ├── test_basic.py               # 8 tests: imports, CHP gates, orchestrator
│   ├── test_consensus.py           # 42 tests: client, routing, adapter, council, models
│   ├── test_skillopt.py            # 28 tests: SKILLOPT optimizer, registry, buffer, hierarchical merge, rewrite mode, protected sections
│   ├── test_council_quality.py     # 33 tests: quality gate, learning loop, R0, disclosure
│   └── test_chp_canonical.py      # 34 tests: canonical CHP core, protocol, agent
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
| 4 atomic edit ops (append/insert_after/replace/delete) | `EditOp` enum with INSERT_AFTER for positional edits |
| Protected slow-update section | `SLOW_UPDATE_START/END` markers immune to step-level edits |
| Hierarchical failure-priority merge | `merge_edits_hierarchical()` with 70/30 failure/success budget |
| Patch + rewrite modes | `EditMode.PATCH` / `EditMode.REWRITE` in TrainingConfig |
| Rollout batch accumulation | `accumulation_batches` config for multi-batch reflection |

### 6. Full Metadata on Every Post

Every child post in the decision room carries Consensus Commons metadata (agent, confidence, produces, consumes, lock_state, trace_id). This is the `payload` field on the Spacebase1 INTENT act — proving the system is native to nested intent spaces.

---

## Running Tests

```bash
cd consensus-commons
PYTHONPATH=src python -m pytest tests/ -v
```

**195 tests** covering:
- MockSpacebaseClient operations (scan, post, enter, lock states, idempotency)
- IntentRouter classification (finance, strategy, general, reject, custom policies)
- SpacebaseAdapter integration (scan, enter, post_child, run_council)
- CouncilRunner orchestration (multi-agent, adversarial, validator, lock lifecycle)
- Data models (Intent, Post, PostTree, LockState serialization)
- End-to-end integration (full council lifecycle, failed validation)
- SKILLOPT skill optimization (edit budget, merge, training loop, validation gate)
- SKILLOPT INSERT_AFTER edit operation (positional insertion without section headers)
- SKILLOPT protected slow-update sections (SLOW_UPDATE_START/END markers)
- SKILLOPT hierarchical failure-priority merge (70/30 failure/success budget split)
- SKILLOPT rewrite mode (full skill rewrite vs localized patch edits)
- SKILLOPT rollout batch accumulation (multi-batch reflection before editing)
- Champion registry (promotion, rejection, persistence)
- Rejected edit buffer (adversarial memory, persistence, optimizer context)
- Session splitter (stratified train/sel/test splits)
- SKILLOPT lock state transitions (EXPLORING through LOCKED path)
- Council Quality Gate (7 dimensions: source grounding, finance logic, materiality, continuity, open issues, learning candidates, human approval)
- Council Learning Loop (propose, approve, reject, apply lifecycle)
- R0 Gate (solvable, scoped, valid, worth-it first-gate checks)
- Foundation Disclosure (weakest assumptions, invalidation conditions, key vulnerabilities)
- Canonical CHP core (DecisionCase, Dossier, gates, payloads, registry, validators, orchestrator)
- Cognitive Mesh Protocol (expansion/compression reasoning, grounding checks, hallucination detection)
- MeshAgent base class (domain specialization, protocol integration)

---

## R0 Gate

The R0 Gate is the first gate every decision intent must pass **before** entering the council pipeline. It prevents waste of computational resources by filtering out unanswerable, overly broad, malformed, or trivial questions.

| Check | What It Evaluates | Failure Example |
|---|---|---|
| **Solvable** | Can agents meaningfully answer this? | "What is the meaning of life?" |
| **Scoped** | Is the scope specific enough? | "How should we restructure everything?" |
| **Valid** | Are inputs well-formed? | Contradictory language in intent |
| **Worth It** | Worth multi-agent compute? | Single-word queries, trivial yes/no |

Implementation: `src/cme/r0_gate.py` — fully rule-based, zero LLM dependency.

## Council Quality Gate

After a council run completes (Phase 5), the CouncilQualityGate evaluates the output through **7 independent quality dimensions**:

| Dimension | What It Measures | Key Signals |
|---|---|---|
| **Source Grounding** | Are claims backed by evidence? | Evidence keywords, body lengths, metadata |
| **Finance Logic** | Does reasoning hold up? | Financial keywords, quantitative data |
| **Materiality** | Focus on what matters | Post count, agent diversity, conclusion state |
| **Continuity** | Prior decisions consistent? | Trace ID consistency, lock progression |
| **Open Issues** | Assumptions vs. facts? | Assumption language, adversarial presence |
| **Learning Candidates** | Improvement signals? | Improvement-oriented language, conditions |
| **Human Approval** | Items needing sign-off? | Human review keywords, auto-lock flags |

Each dimension produces a 0.0–1.0 score. Critical and warning failures block overall pass. Implementation: `src/cme/council_quality_gate.py`.

## Foundation Disclosure

Every council run produces a **foundation disclosure** — an explicit statement of the weakest assumptions underlying the consensus:

- **1–3 Weakest Assumptions** — assumptions most likely to break the conclusion
- **1–2 Invalidation Conditions** — conditions that would invalidate the consensus
- **1 Key Vulnerability** — the most significant deliberation process risk

The disclosure analyses agreement levels (high agreement = possible groupthink), challenge severity, evidence gaps, and missing agent perspectives. Implementation: `src/cme/foundation_disclosure.py`.

## Council Learning Loop

The CouncilLearningLoop implements a **closed-loop self-improvement cycle** for multi-agent deliberations. Every council run produces learning candidates that flow through a well-defined lifecycle:

```
PENDING_REVIEW ──> APPROVED ──> APPLIED to Next Cycle
       │
       └──> REJECTED
       └──> NEEDS_REWRITE
```

Learning candidates are generated from quality gate failures and low-scoring dimensions. The `get_cycle_improvement_report()` method produces a markdown summary of improvement trends across recent cycles. Implementation: `src/cme/council_learning.py`.

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

- **SkillOpt: Executive Strategy for Self-Evolving Agent Skills** — Yifan Yang, Ziyang Gong, Weiquan Huang, Qihao Yang, Ziwei Zhou, Zisu Huang, Yan Li, Xuemei Gao, Qi Dai, Bei Liu, Kai Qiu, Yuqing Yang, Dongdong Chen, Xue Yang, Chong Luo. Microsoft Research / Shanghai Jiao Tong University / Tongji University / Fudan University, May 2026. [arXiv:2605.23904](https://arxiv.org/abs/2605.23904) | [DOI:10.48550/arXiv.2605.23904](https://doi.org/10.48550/arXiv.2605.23904) | [Code](https://aka.ms/SkillOpt)

  The ACE (Agentic Context Engineering) subsystem's playbook evolution loop is directly informed by SKILLOPT's framework for treating skill documents as the external state of a frozen LLM agent, optimized through bounded textual edits, held-out validation gates, learning-rate budgets, and epoch-wise momentum updates. SKILLOPT demonstrated SOTA on all 52 evaluated cells across 7 target models (GPT-5.5, GPT-5.4, GPT-5.4-mini, GPT-5.4-nano, GPT-5.2, Qwen3.5-4B, Qwen3.6-35B-A3B), 3 harnesses (direct chat, Codex, Claude Code), and 6 benchmarks (SearchQA, SpreadsheetBench, OfficeQA, DocVQA, LiveMathematicianBench, ALFWorld). On GPT-5.5 it lifts average no-skill accuracy by +23.5 points in direct chat, +24.8 inside Codex, and +19.1 inside Claude Code.

  Specific SKILLOPT concepts adopted in this repository:

  - **Textual learning rate (L_t)**: Implemented as a per-step edit budget in the `SkillOptimizer`, controlling how many edits the Curator can propose per optimization step. Uses cosine annealing, linear decay, constant, or autonomous schedules with configurable L_max and L_floor parameters.
  - **Validation gate (D_sel)**: The champion registry's `try_promote()` method enforces strict champion-vs-candidate comparison on the held-out selection split. Ties are explicitly rejected (candidate must *strictly* beat the champion), preventing stagnation.
  - **Rejected-edit buffer**: Failed candidate edits are retained as adversarial memory in the `RejectedEditBuffer`, providing the TriangulationRunner with concrete examples of what didn't work — analogous to SKILLOPT's adversarial memory mechanism.
  - **Epoch-wise meta update**: The training loop's epoch structure supports cross-epoch slow/meta update momentum, where successful edit patterns from earlier epochs inform later optimization steps. Protected sections delimited by `SLOW_UPDATE_START`/`SLOW_UPDATE_END` markers are immune to step-level edits.
  - **Curator/optimizer separation**: The Curator proposes edits while a separate optimization process evaluates them on held-out data, mirroring SKILLOPT's separation of the optimizer model from the target model.
  - **4 atomic edit operations**: `EditOp` enum supports `APPEND`, `INSERT_AFTER`, `REPLACE`, and `DELETE` — matching SKILLOPT's full set of textual edit primitives (append, insert_after, replace, delete).
  - **Hierarchical failure-priority merge**: `merge_edits_hierarchical()` mirrors SKILLOPT's batch merge strategy — failure and success edits are analyzed separately, deduplicated independently, and merged with failure patches given priority (~70% budget allocation).
  - **Patch and rewrite modes**: `EditMode.PATCH` (localized bounded edits) and `EditMode.REWRITE` (full skill rewrite from suggestions) map to SKILLOPT's two training modes, with rewrite preserving protected slow-update sections across rewrites.
  - **Rollout batch accumulation**: `accumulation_batches` in `TrainingConfig` allows accumulating multiple rollout batches before reflecting — decoupling execution throughput from update frequency.

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

