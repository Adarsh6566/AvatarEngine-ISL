import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
} from "@pixiv/three-vrm-animation";
import type { VRM } from "@pixiv/three-vrm";
import type { AnimationClip } from "three";

export class VRMAGestureLoader {
  private readonly loader = new GLTFLoader();

  constructor() {
    this.loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
  }

  async load(vrm: VRM, url: string): Promise<AnimationClip> {
    const gltf = await this.loader.loadAsync(url);

const vrmAnimation = gltf.userData.vrmAnimations?.[0];
if (!vrmAnimation) {
  throw new Error(`"${url}" does not contain VRM animation data.`);
}

return createVRMAnimationClip(vrmAnimation, vrm);
  }
}