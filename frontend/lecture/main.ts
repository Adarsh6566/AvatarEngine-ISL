import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RenderEngine } from '../core/RenderEngine';
import { VrmLoader } from '../avatar/loading/VrmLoader';
import { SkeletonRetargeter } from '../avatar/animation/SkeletonRetargeter';
import {
  loadSkeletonStream,
  toViewSpace,
  type SkeletonJointValue,
  type SkeletonStream,
  type SkeletonStreamFrame,
} from '../skeleton/SkeletonStream';
import { matchSigns, type SignMatch } from '../signer/SignLibrary';
import { translateTranscript } from './glossBatch';
import { AVATAR, fitToChrome } from '../avatar/framing/fitToChrome';
import { hideLegs } from '../avatar/framing/hideLegs';
import type { VRM } from '@pixiv/three-vrm';

/**
 * Composition root for the LECTURE signer.
 *
 * A lecture video plays, and the avatar signs each phrase as the lecturer
 * reaches it. Transcription happens in lecture/ (:8002); the sign vocabulary
 * stays here, because it already lives in SignLibrary and a second copy on the
 * server would be a second thing to keep correct.
 *
 * Playback is driven by the VIDEO, not by a timer. The lecturer can be paused,
 * scrubbed or replayed, and the signing has to follow — so what is signed is a
 * function of video.currentTime rather than of elapsed wall time.
 */

const API = (() => {
  const override = new URLSearchParams(window.location.search).get('api');
  return (override ?? 'http://127.0.0.1:8002').replace(/\/$/, '');
})();

// --- DOM ---------------------------------------------------------------------
const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const video = el<HTMLVideoElement>('video');
const fileInput = el<HTMLInputElement>('file');
const chooseBtn = el<HTMLButtonElement>('choose');
const transcribeBtn = el<HTMLButtonElement>('transcribe');
const statusEl = el<HTMLSpanElement>('status');
const transcriptEl = el<HTMLDivElement>('transcript');
const captionEl = el<HTMLDivElement>('caption');
const glossEl = el<HTMLDivElement>('gloss');
const captionRoot = captionEl.closest<HTMLDivElement>('.caption')!;
const resetViewBtn = el<HTMLButtonElement>('reset-view');
const lecturerImg = el<HTMLImageElement>('lecturer');
const urlInput = el<HTMLInputElement>('url');
const fetchBtn = el<HTMLButtonElement>('fetch');
const sourceEl = el<HTMLDivElement>('source');

const meta = {
  file: el<HTMLElement>('m-file'),
  lang: el<HTMLElement>('m-lang'),
  dur: el<HTMLElement>('m-dur'),
  segs: el<HTMLElement>('m-segs'),
  cov: el<HTMLElement>('m-cov'),
  model: el<HTMLElement>('m-model'),
  note: el<HTMLElement>('m-note'),
};

// --- avatar ------------------------------------------------------------------
const mount = el<HTMLDivElement>('avatar');
const engine = new RenderEngine({
  container: mount,
  background: 0xf2efe9,
  camera: { fov: 30, position: [0, 1.35, 4.2], target: [0, 1.2, 0] },
});
engine.add(new THREE.AmbientLight(0xffffff, 1.5));
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(1, 1.6, 1.4);
engine.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.7);
fill.position.set(-1.4, 0.6, 0.8);
engine.add(fill);

/*
 * Let the viewer move the camera.
 *
 * This pane is the smallest of the three — on a phone it is about 267px tall —
 * and a fixed head-on shot at that size makes a handshape hard to read. The
 * other two pipelines have had orbit since they were written; this one never
 * got it.
 *
 * Rotate and zoom only. Panning is off deliberately: it is the one gesture that
 * can carry the avatar off screen entirely, and on a touch screen it shares
 * two fingers with the pinch that zooms. The distance and polar limits exist
 * for the same reason — every reachable camera still has the avatar in it, so
 * there is no way to get lost, and Reset view is a way back rather than a
 * rescue.
 */
const controls = new OrbitControls(engine.camera, engine.domElement);
controls.enableDamping = true;
controls.enablePan = false;
controls.minDistance = 1.6;   // closer than this and the near plane clips the face
controls.maxDistance = 8;
controls.minPolarAngle = Math.PI * 0.12;  // not looking straight down the crown
controls.maxPolarAngle = Math.PI * 0.62;  // not up through the floor
engine.onUpdate(() => controls.update());

const retargeter = new SkeletonRetargeter({ fingerMode: 'full', fingerSmoothing: 0.9 });

/*
 * Keep the avatar clear of the caption.
 *
 * The caption floats over this pane, so the space actually available to the
 * avatar is what remains below it. That matters more here than on the other
 * pipelines because THIS pane is resizable: the user drags the splitter and its
 * height changes arbitrarily, while the caption stays a fixed number of pixels.
 * A framing chosen once at load is wrong as soon as the pane is dragged.
 *
 * The framed band comes from AVATAR — waist to crown, shared with the other
 * two pipelines.
 */
const MIN_DISTANCE = 4.2; // the framing this pane has always used

/*
 * Auto-framing yields to the viewer, permanently, the moment they move the
 * camera.
 *
 * fitToChrome sets camera.position outright, and this pane re-frames on every
 * resize — which the splitter causes on every drag, and the Source toggle
 * causes too. Left alone the two fight, and the fight is not subtle: any orbit
 * or zoom is thrown away the next time the pane changes size, which on a phone
 * is constantly. So once `adjusted` is set nothing here touches the camera
 * again, and Reset view is what hands framing back.
 */
let adjusted = false;

function frameCamera(): void {
  if (adjusted) return;
  const word = captionEl;
  const previous = word.textContent;
  // Measure at a worst case: the caption is empty while idle and grows when a
  // phrase starts, so measuring it as-found would shift the camera mid-sign.
  word.textContent = 'good afternoon';
  try {
    fitToChrome({
      container: mount,
      camera: engine.camera,
      // Handing the controls over keeps their target on the framed centre, so
      // a first drag orbits around the avatar rather than swinging it out of
      // shot around a stale origin.
      controls,
      top: captionRoot,
      bottom: null, // nothing floats over the bottom of this pane
      feetY: AVATAR.signingFloorY,
      headY: AVATAR.crownY,
      minDistance: MIN_DISTANCE,
      rise: 0.15,
    });
  } finally {
    word.textContent = previous;
  }
}

// 'start' fires on a real pointer gesture only — unlike 'change', which
// fitToChrome's own controls.update() would raise and which would therefore
// disable auto-framing the instant the page loaded.
controls.addEventListener('start', () => {
  adjusted = true;
  resetViewBtn.hidden = false;
});

resetViewBtn.addEventListener('click', () => {
  adjusted = false;
  frameCamera();
  resetViewBtn.hidden = true;
});

frameCamera();
try {
  new ResizeObserver(() => frameCamera()).observe(mount);
} catch {
  window.addEventListener('resize', frameCamera);
}

let vrm: VRM | null = null;

// --- playback ----------------------------------------------------------------
let playing: { stream: SkeletonStream; cursor: number } | null = null;
let onSignDone: (() => void) | null = null;
let signWatchdog: ReturnType<typeof setTimeout> | null = null;

const streams = new Map<string, SkeletonStream>();

async function stream(path: string): Promise<SkeletonStream> {
  const cached = streams.get(path);
  if (cached) return cached;
  const loaded = toViewSpace(await loadSkeletonStream(path));
  streams.set(path, loaded);
  return loaded;
}

function finishSign(): void {
  const current = playing;
  playing = null;
  if (signWatchdog !== null) {
    clearTimeout(signWatchdog);
    signWatchdog = null;
  }
  if (current && vrm) {
    const frames = current.stream.frames;
    retargeter.applyPose(vrm, frames[frames.length - 1].joints);
  }
  const done = onSignDone;
  onSignDone = null;
  done?.();
}

type Joints = SkeletonStreamFrame['joints'];

/** Between two captured frames — clips are 25fps, the display is not. */
function lerpJoints(a: Joints, b: Joints, t: number): Joints {
  const out: Record<string, SkeletonJointValue> = {};
  for (const name of Object.keys(a)) {
    const p = a[name];
    const q = b[name];
    out[name] = p && q
      ? [
          p[0] + (q[0] - p[0]) * t,
          p[1] + (q[1] - p[1]) * t,
          p[2] + (q[2] - p[2]) * t,
          p[3] + (q[3] - p[3]) * t,
        ]
      : p;
  }
  return out;
}

engine.onUpdate((delta) => {
  if (!vrm) return;
  if (playing) {
    const { stream: s } = playing;
    playing.cursor += delta * s.fps;
    if (playing.cursor >= s.frames.length - 1) {
      playing.cursor = s.frames.length - 1;
      finishSign();
    } else {
      const i = Math.floor(playing.cursor);
      const t = playing.cursor - i;
      retargeter.applyPose(
        vrm,
        t < 1e-4 ? s.frames[i].joints : lerpJoints(s.frames[i].joints, s.frames[i + 1].joints, t),
      );
    }
  }
  vrm.update(delta);
});

function playSign(s: SkeletonStream): Promise<void> {
  return new Promise((resolve) => {
    retargeter.reset();
    playing = { stream: s, cursor: 0 };
    onSignDone = resolve;
    if (signWatchdog !== null) clearTimeout(signWatchdog);
    // requestAnimationFrame stops in a hidden tab; without this the queue would
    // wedge and nothing after it would ever sign.
    const expected = (s.frames.length / s.fps) * 1000;
    signWatchdog = setTimeout(() => {
      if (playing?.stream === s) finishSign();
    }, expected * 2 + 1500);
  });
}

function setCaption(text: string, gloss: string): void {
  captionEl.textContent = text;
  glossEl.textContent = gloss;
  captionRoot.dataset.state = text ? 'active' : '';
}

// --- sign queue --------------------------------------------------------------
// A lecturer does not wait. Phrases arrive as the video reaches them, and one
// may still be signing when the next is due, so they queue rather than drop.
const queue: SignMatch[] = [];
let busy = false;

function enqueue(matches: readonly SignMatch[]): void {
  queue.push(...matches);
  void drain();
}

async function drain(): Promise<void> {
  if (busy) return;
  busy = true;
  try {
    while (queue.length) {
      const match = queue.shift();
      if (!match) continue;
      setCaption(match.text, match.entry.gloss);
      try {
        await playSign(await stream(match.entry.path));
      } catch (error) {
        console.error('[lecture]', error);
      }
    }
  } finally {
    setCaption('', '');
    busy = false;
  }
}

// --- transcript --------------------------------------------------------------
interface Segment {
  readonly start: number;
  readonly end: number;
  readonly text: string;
}

interface Planned {
  readonly segment: Segment;
  // Not readonly: the string matcher fills this immediately, then batch
  // translation replaces it as better answers arrive.
  matches: SignMatch[];
  readonly row: HTMLElement;
  fired: boolean;
}

let plan: Planned[] = [];

const clock = (t: number) =>
  `${String(Math.floor(t / 60)).padStart(2, '0')}:${(t % 60).toFixed(1).padStart(4, '0')}`;

function render(segments: Segment[]): Planned[] {
  transcriptEl.textContent = '';
  return segments.map((segment) => {
    const matches = matchSigns(segment.text);
    const row = document.createElement('div');
    row.className = 'seg';
    row.innerHTML =
      `<span class="seg__time">${clock(segment.start)}</span>` +
      `<span class="seg__text"></span>` +
      `<span class="seg__signs"></span>`;
    row.querySelector('.seg__text')!.textContent = segment.text;
    const signs = row.querySelector('.seg__signs')!;
    if (matches.length) {
      signs.innerHTML = matches.map((m) => `<b>${m.entry.gloss}</b>`).join(' ');
    } else {
      signs.innerHTML = '<i>no sign</i>';
    }
    // Clicking a line jumps the video there, which is how you check one phrase
    // without watching the whole lecture again.
    row.addEventListener('click', () => {
      video.currentTime = segment.start;
    });
    transcriptEl.append(row);
    return { segment, matches, row, fired: false };
  });
}

/**
 * Sign whatever the lecturer has reached, and nothing they have not.
 *
 * Driven by currentTime rather than by a timer so scrubbing behaves: seeking
 * backwards re-arms the segments after the new position, and seeking forwards
 * does not fire everything that was skipped over.
 */
function syncToVideo(): void {
  const t = video.currentTime;
  for (const item of plan) {
    const active = t >= item.segment.start && t < item.segment.end;
    item.row.dataset.active = String(active);
    if (active && !item.fired) {
      item.fired = true;
      if (item.matches.length) enqueue(item.matches);
    }
    // Rewinding past a segment makes it eligible again.
    if (t < item.segment.start && item.fired) item.fired = false;
  }
}

video.addEventListener('timeupdate', syncToVideo);
video.addEventListener('seeked', syncToVideo);

// --- wiring ------------------------------------------------------------------
let chosen: File | null = null;

chooseBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0] ?? null;
  chosen = file;
  if (!file) return;
  video.src = URL.createObjectURL(file);
  transcribeBtn.disabled = false;
  meta.file.textContent = file.name;
  statusEl.textContent = '';
  plan = [];
  transcriptEl.textContent = '';
  lecturerImg.style.display = 'none';
  meta.note.textContent = '';
});


/**
 * Improve the matcher's results with real translation, in the background.
 *
 * Runs AFTER the transcript is already rendered and playable. Every row starts
 * with whatever the string lookup found, and rows are replaced in place as
 * batches come back — so the page is usable from the first frame and simply
 * gets better, rather than showing a spinner while a language model works
 * through two and a half thousand segments.
 */
let upgradeRun: AbortController | null = null;

async function upgradeWithTranslation(): Promise<void> {
  upgradeRun?.abort(); // a new transcript supersedes any run still going
  const run = new AbortController();
  upgradeRun = run;

  const texts = plan.map((p) => p.segment.text);
  if (!texts.length) return;

  await translateTranscript(
    texts,
    (from, batch) => {
      batch.forEach((matches, i) => {
        const item = plan[from + i];
        if (!item) return;
        // Only replace when translation actually found something. An empty
        // result may be correct, but it may equally be a model that gave up on
        // that sentence — and discarding a match the string lookup already had
        // would make the page worse for no reason.
        if (matches.length === 0) return;
        item.matches = matches;
        const signs = item.row.querySelector('.seg__signs');
        if (signs) signs.innerHTML = matches.map((m) => `<b>${m.entry.gloss}</b>`).join(' ');
      });
      // The coverage figure is the honest measure of this pipeline, so it has to
      // track the upgrade rather than report the matcher's number forever.
      const signable = plan.filter((p) => p.matches.length).length;
      meta.cov.textContent = plan.length
        ? `${signable} / ${plan.length} segments (${Math.round((signable / plan.length) * 100)}%)`
        : '–';
    },
    ({ done, total, improved }) => {
      if (run.signal.aborted) return;
      meta.note.textContent =
        done < total ? `Translating ${done}/${total}…` : `Translated — ${improved} segments signable.`;
    },
    run.signal,
  );
}

function applyTranscript(data: any): void {
  plan = render(data.segments as Segment[]);
  void upgradeWithTranslation();
  const signable = plan.filter((p) => p.matches.length).length;
  meta.lang.textContent = `${data.language} (${data.language_probability})`;
  meta.dur.textContent = `${data.duration}s`;
  meta.segs.textContent = String(plan.length);
  meta.cov.textContent = plan.length
    ? `${signable} / ${plan.length} segments (${Math.round((signable / plan.length) * 100)}%)`
    : '–';
  meta.model.textContent = data.model;

  if (data.lecturer) {
    lecturerImg.src = `${API}${data.lecturer.url}`;
    lecturerImg.style.display = 'block';
    meta.note.textContent = `Lecturer found at ${data.lecturer.timestamp}s.`;
  } else {
    lecturerImg.style.display = 'none';
    meta.note.textContent =
      'No lecturer found in frame — the video may be slides or animation with a voice-over.';
  }

  // A fetched video carries its own terms. This pipeline reuses the speaker's
  // likeness, so who published it and under what licence is worth seeing before
  // the result is used anywhere.
  if (data.source) {
    const licence = data.source.license
      ? `<span class="lic">${data.source.license}</span>`
      : '<span class="lic">licence not stated</span>';
    sourceEl.innerHTML =
      `${licence}<br>by ${data.source.uploader}<br>` +
      `<a href="${data.source.webpage_url}" target="_blank" rel="noreferrer noopener">source</a>`;
    sourceEl.style.display = 'block';
  } else {
    sourceEl.style.display = 'none';
  }

  syncToVideo();
}

/**
 * Show a message with the seconds ticking up, until the returned stop() runs.
 *
 * Fetching a URL takes as long as the download does — measured at 114s for a
 * four-minute lecture — and a caption that never changes for two minutes reads
 * as a hang rather than as work in progress. The elapsed count is the only
 * honest signal available, since neither yt-dlp's progress nor Whisper's is
 * visible from here.
 */
function progress(label: string): () => void {
  const started = Date.now();
  const tick = () => {
    const s = Math.round((Date.now() - started) / 1000);
    statusEl.textContent = `${label} ${s}s`;
  };
  tick();
  const timer = window.setInterval(tick, 1000);
  return () => window.clearInterval(timer);
}

fetchBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) return;
  fetchBtn.disabled = true;
  transcribeBtn.disabled = true;
  chooseBtn.disabled = true;
  const stop = progress('Downloading and transcribing — this can take a couple of minutes…');
  try {
    const response = await fetch(
      `${API}/api/transcribe-url?url=${encodeURIComponent(url)}`,
      { method: 'POST' },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? response.status);

    // Play the file the server fetched, NOT the page it came from: a watch-page
    // URL cannot be played by a video element, and signing is driven by this
    // element's currentTime — without real media nothing would fire.
    if (data.media?.url) {
      video.src = `${API}${data.media.url}`;
    } else {
      video.removeAttribute('src');
      video.load();
      statusEl.textContent =
        'Transcribed, but the video could not be served back — signs will not play along.';
    }
    meta.file.textContent = data.original ?? url;
    chosen = null;
    applyTranscript(data);
    stop();
    statusEl.textContent = '';
  } catch (error) {
    stop();
    console.error('[lecture]', error);
    // A dead backend fails as a bare TypeError, which tells the user nothing.
    const hint =
      error instanceof TypeError
        ? `no response from ${API} — is the lecture server running on port 8002?`
        : String(error);
    statusEl.textContent = `Could not fetch that URL — ${hint}`;
  } finally {
    fetchBtn.disabled = false;
    chooseBtn.disabled = false;
    transcribeBtn.disabled = chosen === null;
  }
});

transcribeBtn.addEventListener('click', async () => {
  if (!chosen) return;
  transcribeBtn.disabled = true;
  chooseBtn.disabled = true;
  const stop = progress('Transcribing…');

  try {
    const body = new FormData();
    body.append('file', chosen);
    const response = await fetch(`${API}/api/transcribe`, { method: 'POST', body });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    const data = await response.json();
    applyTranscript(data);
    stop();
    statusEl.textContent = '';
  } catch (error) {
    stop();
    console.error('[lecture]', error);
    statusEl.textContent =
      `Transcription failed — is the lecture server running on ${API}? (${String(error)})`;
  } finally {
    transcribeBtn.disabled = false;
    chooseBtn.disabled = false;
  }
});

// --- boot --------------------------------------------------------------------
new VrmLoader()
  .load('/models/AvatarSample_C.vrm')
  .then((loaded) => {
    vrm = loaded;
    loaded.scene.position.y = 0.2;
    hideLegs(loaded);
    engine.add(loaded.scene);
    retargeter.captureRest(loaded);
    console.info('[lecture] avatar ready');
  })
  .catch((error: unknown) => {
    console.error('[lecture]', error);
    statusEl.textContent = 'Avatar failed to load.';
  });

engine.start();
