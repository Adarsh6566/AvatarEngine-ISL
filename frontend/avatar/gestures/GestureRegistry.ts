import manifest from "../../../data/motion_manifest.json";

/**
 * One gesture the avatar can perform: the id AnimationController registers the
 * clip under (a gloss token like "HELLO"), and the public URL of the .vrma
 * asset that performs it.
 *
 * This type used to live in GestureManifest.ts alongside a hand-written array.
 * That array is gone; the type now lives with the registry that produces it.
 */
export interface GestureManifestEntry {
  /** Gesture id that AnimationController plays (matches GestureCommand.id). */
  readonly id: string;
  /** Public URL of the .vrma asset (served from /public). */
  readonly url: string;
}

/**
 * GestureRegistry — the single seam between the gesture data source and the
 * avatar.
 *
 * It adapts motion_manifest.json — the single source of truth for gesture
 * metadata — into the {id, url} entries AvatarController needs to load and
 * register clips. The manifest is keyed by gloss token and each value carries
 * dataset metadata (motionId, signer, language, …) the avatar does not need;
 * the registry projects that down to just what registration requires.
 *
 * Keeping this adaptation here is what lets AvatarController stay independent of
 * the data source: swapping the JSON for a database or an HTTP endpoint later is
 * a change to this class alone. Data only, no framework — mirrors the plain
 * collaborator classes elsewhere in the module.
 */
export class GestureRegistry {
  /**
   * Every registrable gesture, one per manifest entry, in manifest key order.
   *
   * Order is preserved for readability but is not depended on: clips register
   * into a map keyed by id, so registration is order-independent.
   */
  getAll(): GestureManifestEntry[] {
    return Object.entries(manifest).map(([id, motion]) => ({
      id,
      url: motion.assetPath,
    }));
  }
}
