import * as THREE from 'three';
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
const lecturerImg = el<HTMLImageElement>('lecturer');

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

const retargeter = new SkeletonRetargeter({ fingerMode: 'full', fingerSmoothing: 0.9 });
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
  readonly matches: SignMatch[];
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

transcribeBtn.addEventListener('click', async () => {
  if (!chosen) return;
  transcribeBtn.disabled = true;
  chooseBtn.disabled = true;
  statusEl.textContent = 'Transcribing… (roughly a tenth of the video length)';

  try {
    const body = new FormData();
    body.append('file', chosen);
    const response = await fetch(`${API}/api/transcribe`, { method: 'POST', body });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    const data = await response.json();

    plan = render(data.segments as Segment[]);

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
      meta.note.textContent =
        'No lecturer found in frame — the video may be slides or animation with a voice-over.';
    }

    statusEl.textContent = '';
    syncToVideo();
  } catch (error) {
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
    engine.add(loaded.scene);
    retargeter.captureRest(loaded);
    console.info('[lecture] avatar ready');
  })
  .catch((error: unknown) => {
    console.error('[lecture]', error);
    statusEl.textContent = 'Avatar failed to load.';
  });

engine.start();
