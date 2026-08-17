from dataclasses import dataclass, field


@dataclass
class TurnContext:
    query_embeddings: dict[str, list[float]] = field(default_factory=dict)

