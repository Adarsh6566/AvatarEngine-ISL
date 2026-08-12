import * as THREE from 'three';
import { Clock } from './Clock';

export interface RenderEngineConfig {
  /** Element the canvas mounts into. Its size defines the viewport. */
  container: HTMLElement;
  background?: THREE.ColorRepresentation;
  camera?: {
    fov?: number;
    near?: number;
    far?: number;
    position?: [number, number, number];
    target?: [number, number, number];
  };
  maxPixelRatio?: number;
}

export type UpdateCallback = (delta: number) => void;

export class RenderEngine {
  readonly camera: THREE.PerspectiveCamera;

  private readonly scene = new THREE.Scene();
  private readonly renderer: THREE.WebGLRenderer;
  private readonly container: HTMLElement;
  private readonly clock = new Clock();
  private readonly maxPixelRatio: number;
  private readonly updateCallbacks = new Set<UpdateCallback>();
  private resizeObserver?: ResizeObserver;

  constructor(config: RenderEngineConfig) {
    this.container = config.container;
    this.maxPixelRatio = config.maxPixelRatio ?? 2;
    this.scene.background = new THREE.Color(config.background ?? 0x101014);

    const cam = config.camera ?? {};
    this.camera = new THREE.PerspectiveCamera(cam.fov ?? 35, this.aspect, cam.near ?? 0.1, cam.far ?? 100);
    this.camera.position.set(...(cam.position ?? [0, 1.3, 3.5]));
    this.camera.lookAt(new THREE.Vector3(...(cam.target ?? [0, 1, 0])));

    if (!this.isWebGLAvailable()) {
      this.showFallback('WebGL 2 is not available — avatar cannot be displayed on this device/browser.');
      // Create a dummy renderer so rest of app can still call dispose() etc. without null checks.
      this.renderer = new THREE.WebGLRenderer({ antialias: true });
    } else {
      try {
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch (cause) {
        this.showFallback('Failed to initialize WebGL renderer.');
        throw new Error('WebGL renderer init failed', { cause });
      }
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.maxPixelRatio));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.appendChild(this.renderer.domElement);

    this.applySize();
    try {
      this.resizeObserver = new ResizeObserver(() => this.applySize());
      this.resizeObserver.observe(this.container);
    } catch {
      // ResizeObserver may be unavailable in some test environments — not fatal.
    }

    // Handle context loss (common on mobile / tab switch)
    this.renderer.domElement.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      console.warn('[RenderEngine] WebGL context lost');
      this.clock.pause();
    });
    this.renderer.domElement.addEventListener('webglcontextrestored', () => {
      console.info('[RenderEngine] WebGL context restored');
      this.clock.resume();
      this.applySize();
    });
  }

  /** Add an object (e.g. the loaded avatar, lights) to the scene. */
  add(object: THREE.Object3D): void {
    this.scene.add(object);
  }

  remove(object: THREE.Object3D): void {
    this.scene.remove(object);
  }

  /** The canvas element — needed by debug controls, screenshots, DOM events. */
  get domElement(): HTMLCanvasElement {
    return this.renderer.domElement;
  }
  onUpdate(callback: UpdateCallback): () => void {
    this.updateCallbacks.add(callback);
    return () => this.updateCallbacks.delete(callback);
  }

  start(): void {
    this.renderer.setAnimationLoop(() => this.frame());
  }

  stop(): void {
    this.renderer.setAnimationLoop(null);
  }

  /** Release GPU resources and DOM listeners. Always call on teardown. */
  dispose(): void {
    this.stop();
    try {
      this.resizeObserver?.disconnect();
    } catch {
      // ignore disconnect failures
    }
    try {
      this.renderer.dispose();
    } catch {
      // ignore dispose failures (context already lost)
    }
    try {
      this.renderer.domElement.remove();
    } catch {
      // already removed
    }
  }

  private isWebGLAvailable(): boolean {
    try {
      const canvas = document.createElement('canvas');
      return !!(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
    } catch {
      return false;
    }
  }

  private showFallback(message: string): void {
    const el = document.createElement('div');
    el.className = 'render-fallback';
    el.setAttribute('role', 'alert');
    el.textContent = message;
    el.style.cssText =
      'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
      'background:#fff;border:1px solid rgba(22,19,15,0.12);padding:16px 20px;' +
      'border-radius:12px;max-width:90vw;text-align:center;z-index:100;' +
      'font-family:var(--font-display, sans-serif);color:#16130f;';
    document.body.append(el);
  }

  private frame(): void {
    const delta = this.clock.tick();
    for (const callback of this.updateCallbacks) callback(delta);
    this.renderer.render(this.scene, this.camera);
  }

  private get aspect(): number {
    return this.container.clientWidth / Math.max(this.container.clientHeight, 1);
  }

  private applySize(): void {
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    this.camera.aspect = this.aspect;
    this.camera.updateProjectionMatrix();
  }
}
