"""Minimal context engine stub for CHP orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Entity:
    id: str
    type: str
    attributes: Dict[str, Any] = field(default_factory=dict)


class ContextEngine:
    """In-memory context engine for organizational knowledge."""

    def __init__(self) -> None:
        self._entities: Dict[str, Entity] = {}
        self._memories: List[Dict[str, Any]] = []
        self._events: List[Dict[str, Any]] = []

    def upsert_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity

    def write(
        self,
        content: str,
        source_agent: str = "",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> None:
        self._memories.append({
            "content": content,
            "source_agent": source_agent,
            "importance": importance,
            "tags": tags or [],
        })

    def select(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        scored = []
        for mem in self._memories:
            content = mem.get("content", "").lower()
            score = sum(1 for word in query_lower.split() if word in content)
            if score > 0:
                scored.append((score, mem))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:k]]

    def snapshot_for(self, agent_name: str, problem: str, k: int = 6) -> Dict[str, Any]:
        hits = self.select(problem, k=k)
        return {
            "agent": agent_name,
            "relevant_memories": hits,
            "problem": problem,
        }

    def record_event(
        self,
        actor: str,
        action: str,
        object_: str = "",
        confidence: str = "",
    ) -> None:
        self._events.append({
            "actor": actor,
            "action": action,
            "object": object_,
            "confidence": confidence,
        })

    def find_related(self, text: str) -> list:
        """Stub for registry integration — returns empty list."""
        return []
