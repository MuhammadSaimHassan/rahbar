"""Read-only resolution of the logical index to an immutable generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveIndex:
    collection: str
    generation: str


def resolve_index(logical: str, value: str | None) -> ActiveIndex:
    if value is None:
        return ActiveIndex(logical, "bootstrap")
    catalog = json.loads(value)
    if not isinstance(catalog, dict):
        raise ValueError("invalid active catalog")
    collection, generation = catalog["collection"], catalog["generation"]
    if not isinstance(collection, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]", collection):
        raise ValueError("invalid active collection")
    if not isinstance(generation, str) or not re.fullmatch(r"[a-f0-9]{32}", generation):
        raise ValueError("invalid active generation")
    return ActiveIndex(collection, generation)
