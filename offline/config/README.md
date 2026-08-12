# config/ — pipeline configuration

Everything variable lives here as data, not code: target fps, which estimator to
use, the canonical skeleton definition, and retarget profiles (source-skeleton →
VRM humanoid bone maps). Loaded by `motionpipe/config.py` into `PipelineConfig`.

Keeping these external is what lets a new estimator or target rig be added
without touching stage logic.
