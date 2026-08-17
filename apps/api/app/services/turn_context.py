from dataclasses import dataclass, field
from uuid import UUID


SnapshotKey = tuple[UUID, UUID, UUID | None]
MemoryKey = tuple[UUID, UUID, str]


@dataclass
class TurnContext:
    query_embeddings: dict[str, list[float]] = field(default_factory=dict)
    snapshot_states: dict[SnapshotKey, dict | None] = field(default_factory=dict)
    memory_results: dict[MemoryKey, tuple[str, ...]] = field(default_factory=dict)
