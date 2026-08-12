import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm';
/**
 * Loads a .vrm file into a ready-to-use VRM.
 * Hides the loading details from the rest of the engine.
 */
export class VrmLoader {
  private readonly loader = new GLTFLoader();

  constructor() {
    // Enables VRM support in GLTFLoader.
    this.loader.register((parser) => new VRMLoaderPlugin(parser));
  }

  async load(url: string): Promise<VRM> {
    const gltf = await this.readGltf(url);

    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) {
      throw new Error(`"${url}" parsed as glTF but contains no VRM data — is it a real VRM export?`);
    }

    // VRM 0.x avatars face +Z (away from the camera); rotate 180° to face the
    // viewer. No-op for VRM 1.0. (This is the rotateVRM0 you added by hand.)
    VRMUtils.rotateVRM0(vrm);

    // Performance passes, verified against three-vrm 3.5.5:
    //   removeUnnecessaryVertices — strips unused morph-target vertices
    //   combineSkeletons          — merges skeletons; replaces the deprecated
    //                               removeUnnecessaryJoints
    VRMUtils.removeUnnecessaryVertices(vrm.scene);
    VRMUtils.combineSkeletons(vrm.scene);

    // Skinned meshes animate outside their rest-pose bounds; disabling frustum
    // culling stops limbs/fingers vanishing at the frame edge while signing.
    vrm.scene.traverse((obj) => {
      obj.frustumCulled = false;
    });

    return vrm;
  }

  private async readGltf(url: string) {
    try {
      return await this.loader.loadAsync(url);
    } catch (cause) {
      throw new Error(
        `Could not read a VRM at "${url}". Is the file present and non-empty? ` +
          `(public/models/avatar.vrm is currently 0 bytes — drop a real VRM there.)`,
        { cause },
      );
    }
  }
}
