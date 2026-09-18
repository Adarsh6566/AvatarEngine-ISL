/**
 * SMPL-X experimental viewer (additive, dev-served).
 *
 * Loads skinned+animated GLBs baked by offline/smplx/build_glb.py from the SAME
 * captured motion the VRM path uses, and plays them so the SMPL-X body can be
 * compared against the VRM avatar on identical input.
 *
 * Behaves like signer.html: type text -> translateToSigns() (Ollama via the
 * backend, falling back to the exact matcher) -> the matched signs play once, in
 * order, then stop. The lower half is clipped away (waist-up, like the signer's
 * hideLegs) and the speed control is the same corner widget the signer uses.
 *
 * Self-contained three.js; imports nothing from the VRM/skeleton RENDERERS and
 * modifies no existing code. It reuses signer.html's OWN translate + speed
 * modules read-only so the two pages behave identically.
 */
import * as THREE from 'three';
import { GLTFLoader, OrbitControls } from 'three-stdlib';
import { translateToSigns } from '../signer/glossTranslate';
import { knownPhrases, type SignEntry } from '../signer/SignLibrary';
import { PlaybackSpeedControl } from '../ui/PlaybackSpeedControl';

const app = document.getElementById('app')!;
const hudSign = document.getElementById('signName')!;
const hudSub = document.getElementById('sub')!;
const hudStatus = document.getElementById('status')!;
const msg = document.getElementById('msg')!;
const input = document.getElementById('text') as HTMLInputElement;
const captionEl = document.getElementById('caption')!;
const capWordEl = document.getElementById('capWord')!;    // typed word being translated (large)
const capGlossEl = document.getElementById('capGloss')!;  // library gloss it maps to (small)

const slugOf = (e: SignEntry) => e.path.replace(/^.*\//, '').replace(/\.json$/, '');
document.getElementById('known')!.textContent = 'Knows: ' + knownPhrases().join(' · ');

// Legs are removed in the BAKE (by skin weight — see build_glb.py), so there is
// no spatial clip here: the hands are never cropped, however low they hang. We
// frame down to just below where the hands reach (measured -0.547) so the whole
// signing space stays in view, torso-and-arms with no legs — like the signer.
const VIEW_FLOOR = -0.66;

// --- scene -----------------------------------------------------------------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x33363f);

const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
camera.position.set(0, 0.1, 2);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.2));
const dir = new THREE.DirectionalLight(0xffffff, 1.6);
dir.position.set(1, 2, 2);
scene.add(dir);

function resize() {
  const w = app.clientWidth || innerWidth, h = app.clientHeight || innerHeight;
  // updateStyle defaults to true — it MUST, or the retina drawing buffer (w*dpr)
  // is shown at its own pixel size with no CSS size, overflowing the container and
  // getting clipped to the left, which shoves the centred model off to the right.
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

/**
 * Frame the CROPPED upper body, dead-centre. Target x=z=0 explicitly — the SMPL-X
 * body is symmetric about the vertical axis, so looking straight down it centres
 * the torso regardless of viewport aspect. Vertical span is the clip line up to
 * the crown. Runs once; later signs keep the user's camera.
 */
function frameWaistUp(obj: THREE.Object3D) {
  obj.updateWorldMatrix(true, true);
  const head = obj.getObjectByName('head')?.getWorldPosition(new THREE.Vector3());
  const crown = (head?.y ?? 0.27) + 0.16;
  const targetY = (VIEW_FLOOR + crown) / 2;
  const H = crown - VIEW_FLOOR;
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const dist = (H / 2) / Math.tan(fov / 2) * 1.12;
  controls.target.set(0, targetY, 0);
  camera.position.set(0, targetY, dist);
  camera.near = Math.max(dist / 100, 0.001);
  camera.far = dist * 100;
  camera.updateProjectionMatrix();
  controls.minDistance = 0.2;
  controls.maxDistance = dist * 4;
  controls.update();
}

// --- playback (sign once, then stop; a sequence plays in order) -------------
const loader = new GLTFLoader();
const clock = new THREE.Clock();
let mixer: THREE.AnimationMixer | null = null;
let action: THREE.AnimationAction | null = null;
let current: THREE.Object3D | null = null;
let loadedSlug: string | null = null;
let framed = false;
let playbackRate = 1;
let headBone: THREE.Object3D | null = null;   // for anchoring the caption above the head
let signing = false;                          // caption shows only while a sign plays
const _tmp = new THREE.Vector3();

type Item = { slug: string; gloss: string; word: string };
let queue: Item[] = [];
let qIndex = 0;
let token = 0; // invalidates an in-flight sequence when a new one starts

const showMsg = (html: string | null) => {
  msg.style.display = html ? 'block' : 'none';
  if (html) msg.innerHTML = html;
};
const setSpeed = () => { if (mixer) mixer.timeScale = playbackRate; };

function loadGlb(slug: string): Promise<{ scene: THREE.Object3D; animations: THREE.AnimationClip[] }> {
  return new Promise((res, rej) => loader.load(`/smplx/${slug}.glb`, res as never, undefined, rej));
}

function onFinished() {
  qIndex += 1;
  if (qIndex < queue.length) playNext(token);
  else signing = false;   // sequence done — hold the last pose, clear the caption
}

function playNext(myToken: number) {
  if (myToken !== token) return;           // a newer sequence superseded this one
  const item = queue[qIndex];
  if (!item) return;
  hudSign.textContent = item.gloss;
  hudSub.textContent = `SMPL-X · ${item.slug}.glb`;

  const start = () => {
    if (myToken !== token) return;
    if (!action) return;
    // Like signer.html: the typed word being translated on top, and below it the
    // library gloss it maps to (e.g. "hi" over "HELLO"). Set once per sign.
    capWordEl.textContent = item.word;
    capGlossEl.textContent = item.gloss;
    signing = true;
    action.reset();
    action.loop = THREE.LoopOnce;
    action.clampWhenFinished = true;
    action.paused = false;
    action.play();
    setSpeed();
  };

  // Same body across signs: only reload when the sign actually changes.
  if (item.slug === loadedSlug && action && mixer) { start(); return; }

  loadGlb(item.slug).then((gltf) => {
    if (myToken !== token) return;
    showMsg(null);
    if (current) scene.remove(current);
    mixer?.stopAllAction();
    current = gltf.scene;
    loadedSlug = item.slug;
    scene.add(current);
    headBone = current.getObjectByName('head') ?? null;
    mixer = new THREE.AnimationMixer(current);
    mixer.addEventListener('finished', onFinished);
    action = gltf.animations.length ? mixer.clipAction(gltf.animations[0]) : null;
    if (!framed) { frameWaistUp(current); framed = true; }
    start();
  }).catch(() => showMsg(
    `<b>${item.gloss}</b> isn't baked yet.<br>Generate it with:<br>` +
    `<code>python offline/smplx/build_glb.py --sign ${item.slug}</code>`,
  ));
}

/** Type-to-sign, exactly like signer.html: Ollama translate (falls back to the
 *  exact matcher), then play the matched sign(s) once, in order. Unknown words
 *  are dropped by the translator/matcher, not signed. */
async function submit(text: string) {
  hudStatus.textContent = 'Translating…';
  const { matches, source } = await translateToSigns(text);
  if (matches.length === 0) {
    hudStatus.textContent = text.trim() ? 'No captured sign for that — try a phrase below.' : '';
    return;
  }
  hudStatus.textContent = source === 'llm' ? 'translated' : 'matched';
  queue = matches.map((m) => ({ slug: slugOf(m.entry), gloss: m.entry.gloss, word: m.text }));
  qIndex = 0;
  token += 1;
  playNext(token);
}

document.getElementById('signBtn')!.addEventListener('click', () => submit(input.value));
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(input.value); });

// Same corner speed widget the signer uses (full ladder from config.yaml).
new PlaybackSpeedControl(document.body, {
  clearOf: '#bar',
  onChange: (s) => { playbackRate = s; setSpeed(); },
});

renderer.setAnimationLoop(() => {
  mixer?.update(clock.getDelta());
  controls.update();

  // Caption above the head, tracking it in 3-D, shown only while a sign plays.
  if (signing && headBone) {
    headBone.getWorldPosition(_tmp);
    _tmp.y += 0.14;                 // sit just above the crown
    _tmp.project(camera);           // world -> normalised device coords
    if (_tmp.z < 1) {              // in front of the camera
      captionEl.style.left = `${(_tmp.x * 0.5 + 0.5) * app.clientWidth}px`;
      captionEl.style.top = `${(-_tmp.y * 0.5 + 0.5) * app.clientHeight}px`;
      captionEl.classList.add('show');
    } else {
      captionEl.classList.remove('show');
    }
  } else {
    captionEl.classList.remove('show');
  }

  renderer.render(scene, camera);
});

/** Show the avatar standing idle (a sign's first frame, not playing) so the page
 *  never opens on an empty scene, while the textbox stays empty. */
function showIdle(slug = 'we') {
  loadGlb(slug).then((gltf) => {
    if (current) scene.remove(current);
    mixer?.stopAllAction();
    current = gltf.scene;
    loadedSlug = slug;
    scene.add(current);
    headBone = current.getObjectByName('head') ?? null;
    mixer = new THREE.AnimationMixer(current);
    mixer.addEventListener('finished', onFinished);
    action = gltf.animations.length ? mixer.clipAction(gltf.animations[0]) : null;
    if (action) {
      action.loop = THREE.LoopOnce; action.clampWhenFinished = true;
      action.play(); action.time = 0; action.paused = true;
    }
    mixer.update(0);                                   // apply the resting first frame
    if (!framed) { frameWaistUp(current); framed = true; }
    signing = false;
    hudSign.textContent = '—'; hudSub.textContent = 'SMPL-X · experiment';
  }).catch(() => {});
}

// Empty textbox by default; ?text=… still auto-plays for a shareable link.
const startText = new URLSearchParams(location.search).get('text');
if (startText) { input.value = startText; submit(startText); }
else { input.value = ''; showIdle(); }
