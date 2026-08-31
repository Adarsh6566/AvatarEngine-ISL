"""Asset-integrity tests for the gesture manifest.

`data/motion_manifest.json` is the single source of truth for gesture metadata
(see docs/ARCHITECTURE.md). Both consumers read it directly — the frontend's
MotionCatalog (gloss -> motion, for the Sequencer) and GestureRegistry
(manifest -> {id, url}, for clip registration). Consolidating to one file killed
a class of drift bug, but the trade-off recorded in that document is that the
manifest is now *load-bearing for the avatar*: a typo in the file edited every
time a word is added can break clip loading.

These tests are the safety net for that trade-off. They check the three edges
where the manifest can disagree with reality:

    A. manifest -> disk      every assetPath resolves to a real file
    B. vocab/alphabet -> manifest   every gloss the backend can emit is playable
    C. disk -> manifest      no .vrma sits unreferenced

Paths come from backend.config (get_manifest_path / get_dictionary_path) rather
than being hardcoded, so these follow config.yaml the same way the app does.
"""

import json
import unittest
from pathlib import Path

from backend.config import get_dictionary_path, get_manifest_path

ROOT = Path(__file__).resolve().parents[1]

# Vite serves `public/` as the web root (frontend/vite.config.ts: publicDir),
# so a manifest assetPath of "/animations/x.vrma" is public/animations/x.vrma.
PUBLIC_DIR = ROOT / "public"
ANIMATIONS_DIR = PUBLIC_DIR / "animations"

# alphabet.json has no config entry — translator.py resolves it relative to
# itself, so we mirror that rather than inventing a config key.
ALPHABET_PATH = ROOT / "backend" / "language" / "alphabet.json"


def _resolve_configured(path_str: str) -> Path:
    """Resolve a config-supplied path the way backend/mapper.py does.

    The value may be absolute, or relative to the repo root or to backend/.
    """
    p = Path(path_str)
    if p.is_absolute():
        return p
    for base in (ROOT, ROOT / "backend"):
        candidate = base / p
        if candidate.exists():
            return candidate
    return ROOT / p


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class AssetIntegrityTest(unittest.TestCase):
    """Guards the manifest against the three ways it can drift from reality."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _load_json(_resolve_configured(get_manifest_path()))
        cls.vocabulary = _load_json(_resolve_configured(get_dictionary_path()))
        cls.alphabet = _load_json(ALPHABET_PATH)

    # --- A. manifest -> disk ------------------------------------------------

    def test_every_manifest_asset_exists_on_disk(self) -> None:
        missing = sorted(
            f"{gloss} -> {entry['assetPath']}"
            for gloss, entry in self.manifest.items()
            if not (PUBLIC_DIR / entry["assetPath"].lstrip("/")).is_file()
        )
        self.assertFalse(
            missing,
            f"{len(missing)} manifest entr(y/ies) point at a file that does not "
            f"exist under {PUBLIC_DIR}:\n  " + "\n  ".join(missing),
        )

    # --- B. vocabulary / alphabet -> manifest -------------------------------

    def test_every_vocabulary_gloss_has_a_manifest_entry(self) -> None:
        # vocabulary.json maps a written word -> gloss token: {"hello": "HELLO"}
        unmapped = sorted(
            f"{word} -> {gloss}"
            for word, gloss in self.vocabulary.items()
            if gloss not in self.manifest
        )
        self.assertFalse(
            unmapped,
            f"{len(unmapped)} vocabulary gloss(es) have no manifest entry, so the "
            f"avatar has no clip to play for them:\n  " + "\n  ".join(unmapped),
        )

    def test_every_alphabet_gloss_has_a_manifest_entry(self) -> None:
        # alphabet.json maps a single character -> gloss token: {"a": "A"}.
        # These are the fingerspelling fallbacks, so a missing one means a word
        # that cannot be mapped also cannot be fully spelled.
        unmapped = sorted(
            f"{character!r} -> {gloss}"
            for character, gloss in self.alphabet.items()
            if gloss not in self.manifest
        )
        self.assertFalse(
            unmapped,
            f"{len(unmapped)} alphabet gloss(es) have no manifest entry, so "
            f"fingerspelling holds the caption with no clip:\n  "
            + "\n  ".join(unmapped),
        )

    # --- C. disk -> manifest ------------------------------------------------

    def test_no_orphan_vrma_assets(self) -> None:
        # Scope is the served sign assets only. dist/ is build output of this
        # same directory, and offline/ holds pipeline products that are copied
        # here by hand once accepted — neither is a source asset.
        referenced = {
            entry["assetPath"].split("/")[-1] for entry in self.manifest.values()
        }
        orphans = sorted(
            path.name
            for path in ANIMATIONS_DIR.glob("*.vrma")
            if path.name not in referenced
        )
        self.assertFalse(
            orphans,
            f"{len(orphans)} .vrma file(s) in {ANIMATIONS_DIR} are not referenced "
            f"by any manifest entry:\n  " + "\n  ".join(orphans),
        )


if __name__ == "__main__":
    unittest.main()
