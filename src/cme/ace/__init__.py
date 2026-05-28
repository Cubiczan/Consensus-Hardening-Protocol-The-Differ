"""Agentic Context Engineering (ACE) — SKILLOPT-style skill optimization loop.

ACE is CHP's self-improving subsystem: Generator produces analysis, Reflector
critiques, Curator edits playbooks. This module adds SKILLOPT-style training
rigor on top of ACE:

  - Bounded textual edit budget (learning-rate analog)
  - Held-out validation gate (D_sel) for playbook promotion
  - Rejected-edit buffer as adversarial memory
  - Champion registry with versioned best_skill.md
  - Epoch-wise slow/meta update (momentum analog)
  - Train/Selection/Test split of historical sessions

Reference:
  Yang et al., "SkillOpt: Executive Strategy for Self-Evolving Agent Skills",
  Microsoft / SJTU / Tongji / Fudan, May 2026. arXiv:2605.23904
"""

from __future__ import annotations

__version__ = "0.2.0"
