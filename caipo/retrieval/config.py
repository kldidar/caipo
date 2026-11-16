"""The chunking configuration, read from its versioned file (ADR-0025 point 5)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

PATH = Path(__file__).with_name("chunking.toml")
TRANSFORMATIONS = ("nfkc", "casefold", "collapse_whitespace")


@dataclass(frozen=True)
class ChunkingConfiguration:
    version: str
    text_search_config: str
    unit: str
    transformations: tuple[str, ...]
    max_query_length: int
    candidates_per_retriever: int
    rrf_k: int
    trigram_threshold: float


def load(path: Path = PATH) -> ChunkingConfiguration:
    """Read the configuration. Raises ValueError if it names anything this code does not do."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    search = data["search"]
    configuration = ChunkingConfiguration(
        version=str(data["version"]),
        text_search_config=str(data["text_search_config"]),
        unit=str(data["unit"]),
        transformations=tuple(str(name) for name in data["transformations"]),
        max_query_length=int(search["max_query_length"]),
        candidates_per_retriever=int(search["candidates_per_retriever"]),
        rrf_k=int(search["rrf_k"]),
        trigram_threshold=float(search["trigram_threshold"]),
    )
    if configuration.unit != "segment":
        raise ValueError(f"Unknown chunking unit: {configuration.unit}")
    unknown = set(configuration.transformations) - set(TRANSFORMATIONS)
    if unknown:
        raise ValueError(f"Unknown search-side transformations: {sorted(unknown)}")
    if not configuration.version or configuration.text_search_config != "english":
        raise ValueError("The version is required, and the corpora are in English.")
    return configuration
