"""Name -> PoseEstimator registry.

Lets `config.estimator` select an implementation by string, so adding an
estimator is: write the module, `register()` it, reference it in config — with no
change to any stage. Concrete estimators self-register on import.
"""
from __future__ import annotations

from .base import PoseEstimator

_ESTIMATORS: dict[str, PoseEstimator] = {}


def register(estimator: PoseEstimator) -> None:
    """Add an estimator under its `.name`. Raises on duplicate names."""
    if estimator.name in _ESTIMATORS:
        raise ValueError(f"estimator already registered: {estimator.name}")
    _ESTIMATORS[estimator.name] = estimator


def get(name: str) -> PoseEstimator:
    """Look up a registered estimator, or raise with the available names."""
    try:
        return _ESTIMATORS[name]
    except KeyError:
        raise KeyError(f"unknown estimator {name!r}; registered: {sorted(_ESTIMATORS)}")


def available() -> list[str]:
    return sorted(_ESTIMATORS)
