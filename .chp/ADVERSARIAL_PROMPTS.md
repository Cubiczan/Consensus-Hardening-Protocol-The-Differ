# Adversarial Challenge Templates — consensus-hardening-protocol-differ

## Phase 0: Foundation Challenge
When a new decision enters CHP, the adversary MUST address:
1. Why is the proposed direction wrong? (vulnerability_strike)
2. What is the system not seeing? (invalidation_conditions)
3. What is the false consensus risk?

## Domain-Specific Challenges (AI / Agents)
1. What failure modes exist in the agent orchestration that could produce silent incorrect outputs?
2. How does context window limitation affect the quality of multi-round decisions?
3. What is the prompt injection or adversarial input risk for the agent system?
4. How does model drift affect long-running agent processes?
5. What is the blast radius if an agent makes an autonomous decision with bad data?

## Round 3: Implementation Drift Check
1. Does the implementation match the locked spec acceptance criteria?
2. Are operational handoffs and owner capacity accounted for?
3. Is evidence quality sufficient for the decision domain?

## Council Spawn Triggers
When confidence <85% on high-stakes decisions:
- Attacker Model 1: Challenge foundational assumptions
- Attacker Model 2: Challenge operational feasibility
- Synthesizer: Resolve contradictions and produce final recommendation
