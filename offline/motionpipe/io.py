"""Artifact persistence — read/write each stage's model to/from output/.

This is what decouples stages: each writes its result and the next reads it, so
stages run standalone and the pipeline is resumable. Format per artifact (json
for metadata, npz for numeric arrays) is decided when implemented.

All functions are contracts only here.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


def write(artifact: Any, path: str | Path) -> None:
    """Serialize a dataclass artifact to `path` as JSON (creating parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(artifact) if dataclasses.is_dataclass(artifact) else artifact
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def read(model: type, path: str) -> Any:
    """Deserialize `path` back into `model`. Not implemented yet."""
    raise NotImplementedError
