# tests/ — stage tests + fixtures

A tiny fixture clip proves the chain end-to-end without the full dataset. Each
stage is a pure function, so tests assert `stage(fixture_input) == expected` at
each boundary. Add tests as stages are implemented.
