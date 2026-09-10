import { useCallback, useEffect, useRef, useState } from 'react';
import { Splitter } from '../ui/Splitter';

/** Layout defaults, and the bounds a drag may not push a pane past. */
const DEFAULT_SPLIT = 0.5;        // video / avatar, as a fraction of the stage
const MIN_SPLIT = 0.15;
const DEFAULT_TRANSCRIPT = 210;   // px
const MIN_TRANSCRIPT = 72;        // one row plus its padding stays legible
const MIN_STAGE = 160;            // the panes never collapse to nothing

/** Remembered per browser so a layout survives a reload. Never leaves the device. */
const STORAGE_KEY = 'lecture.layout.v1';

function loadLayout(): { split: number; transcript: number; sourceOpen: boolean } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (Number.isFinite(v.split) && Number.isFinite(v.transcript)) {
        // The split is a fraction and can be bounded here; the transcript is
        // in pixels and cannot, since nothing is measurable yet — the page
        // ResizeObserver corrects it on the first layout pass.
        return {
          split: Math.min(1 - MIN_SPLIT, Math.max(MIN_SPLIT, v.split)),
          transcript: Math.max(MIN_TRANSCRIPT, v.transcript),
          // Older saves predate this and have no opinion; open is the honest
          // default, since a page that hid its only file picker on first run
          // would be unusable.
          sourceOpen: typeof v.sourceOpen === 'boolean' ? v.sourceOpen : true,
        };
      }
    }
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning null; a missing layout is not worth failing the page over.
  }
  return { split: DEFAULT_SPLIT, transcript: DEFAULT_TRANSCRIPT, sourceOpen: true };
}

/**
 * Chrome for the LECTURE signer, as React + Tailwind.
 *
 * React paints the markup; lecture/main.ts drives it. That module resolves
 * every element by id ONCE at module load — meta.file, meta.cov, sourceEl and
 * the rest are captured into closures — so the ids here are contract, and
 * every one of those elements must stay mounted for the life of the page.
 *
 * That is why the details panel below is hidden with a class rather than
 * conditionally rendered. React reconciliation keeps the same DOM nodes when
 * only an attribute changes, so main.ts's references survive; unmounting the
 * panel when closed would leave it writing to detached elements and the run
 * data would silently stop updating.
 *
 * The .seg transcript rows live in theme.css for the same reason in reverse:
 * they are built by render() in main.ts, so no JSX ever sees them.
 */
export function LectureApp() {
  const started = useRef(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const stageRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLElement>(null);
  const [layout, setLayout] = useState(loadLayout);
  // Below 900px the stage stacks, so the divider between the two panes turns
  // from an upright line dragged sideways into a lying-down one dragged up.
  const [stacked, setStacked] = useState(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void import('./main');
  }, []);

  /*
   * Measure the STAGE, not the viewport.
   *
   * "Is there room for two panes side by side" is a question about the element,
   * and answering it with a media query means answering a different question
   * that merely correlates — it also misses the case where the stage is
   * narrower than the window. A ResizeObserver fires whenever the box actually
   * changes, including on the first layout pass, which a matchMedia listener
   * does not: its initial value has to be read separately and can already be
   * stale by the time React commits.
   */
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const sync = () => setStacked(el.clientWidth < 900);
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    // ResizeObserver callbacks are delivered before paint, so a document that
    // is not painting — a hidden tab, a backgrounded window — can hold them
    // back indefinitely. A resize listener is driven by the event loop instead
    // and arrives regardless. They are redundant on purpose: whichever fires,
    // sync() reads the element and reaches the same answer.
    window.addEventListener('resize', sync);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', sync);
    };
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // Storage can be unavailable or full; the layout still works this session.
    }
  }, [layout]);


  /** Pointer position → the video/avatar split, clamped away from either edge. */
  const dragSplit = useCallback(
    (clientX: number, clientY: number) => {
      const box = stageRef.current?.getBoundingClientRect();
      if (!box) return;
      const raw = stacked
        ? (clientY - box.top) / Math.max(box.height, 1)
        : (clientX - box.left) / Math.max(box.width, 1);
      setLayout((l) => ({ ...l, split: Math.min(1 - MIN_SPLIT, Math.max(MIN_SPLIT, raw)) }));
    },
    [stacked],
  );

  /**
   * Hold a transcript height inside its bounds.
   *
   * Shared by the drag and the keyboard, because they are two ways to set the
   * same value and must not disagree about what it may be. They did: the drag
   * clamped both ends while the arrow keys clamped only the minimum, so holding
   * ArrowUp grew the transcript past the height of the page and collapsed the
   * stage to nothing — with no way to drag it back, the divider having gone off
   * screen with it.
   */
  const clampTranscript = useCallback((px: number) => {
    const page = pageRef.current?.clientHeight ?? 0;
    // The header and the divider itself also occupy rows, so measuring the
    // ceiling against the whole page would promise the stage MIN_STAGE and
    // hand it MIN_STAGE minus the header — about 100px instead of 160.
    const chrome = (headerRef.current?.offsetHeight ?? 0) + 1;
    const ceiling = Math.max(MIN_TRANSCRIPT, page - chrome - MIN_STAGE);
    return Math.min(ceiling, Math.max(MIN_TRANSCRIPT, px));
  }, []);

  /**
   * Pointer position → transcript height.
   *
   * Measured from the BOTTOM of the page, because that is the edge the
   * transcript is anchored to — deriving it from the top would make the value
   * depend on the header's wrapped height, which changes on its own.
   */
  const dragTranscript = useCallback(
    (_clientX: number, clientY: number) => {
      const box = pageRef.current?.getBoundingClientRect();
      if (!box) return;
      setLayout((l) => ({ ...l, transcript: clampTranscript(box.bottom - clientY) }));
    },
    [clampTranscript],
  );

  /*
   * Re-clamp whenever the page itself changes size.
   *
   * A transcript height is only meaningful against a particular viewport. One
   * saved on a desktop monitor is taller than a phone screen, so restoring it
   * verbatim would open the page with the stage crushed to nothing — the same
   * failure the keyboard clamp fixed, arriving by a different route. Rotating
   * a device or dragging a window smaller does it too.
   *
   * Observing the page covers all three, including the first layout pass, which
   * is what corrects a value restored from storage before anything was
   * measurable.
   */
  useEffect(() => {
    const el = pageRef.current;
    if (!el) return;
    const sync = () =>
      setLayout((l) => {
        const transcript = clampTranscript(l.transcript);
        return transcript === l.transcript ? l : { ...l, transcript };
      });
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    window.addEventListener('resize', sync);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', sync);
    };
  }, [clampTranscript]);

  // Dismiss on Escape or a click outside, the way the speed control does.
  useEffect(() => {
    if (!detailsOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDetailsOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!panelRef.current?.contains(target) && target !== triggerRef.current) {
        setDetailsOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('click', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('click', onClick);
    };
  }, [detailsOpen]);

  return (
    <div
      ref={pageRef}
      className="grid h-screen"
      /* Rows: header, stage, its splitter, transcript. The stage takes 1fr so
         it absorbs whatever the transcript is not using. */
      style={{ gridTemplateRows: `auto 1fr auto ${layout.transcript}px` }}
    >
      {/*
        relative so the details panel can hang off the header's bottom edge
        whatever height it wraps to. flex-wrap matters on a phone: a single
        non-wrapping row of a URL field and four buttons cannot go below about
        672px, and width=device-width does not help — the phone just zooms the
        whole page out to fit.
      */}
      <header ref={headerRef} className="relative flex flex-wrap items-center gap-3.5 border-b border-line px-[18px] py-3">
        <span className="mr-auto text-[11px] uppercase tracking-[0.14em] text-muted-soft">
          lecture → sign
        </span>
        <span id="status" className="min-h-[18px] text-[13px] text-accent" />
        <input id="file" type="file" accept="video/*" className="hidden" />

        {/*
          Choosing a source is a once-per-lecture job, and on a phone it cost a
          fifth of the screen to leave on show: measured at 375x812 the header
          wrapped to three rows and stood 175px tall, which left the avatar pane
          213px. Collapsed it is one row, and the panes get that space back.

          Hidden with a class, never unmounted — main.ts captured #url, #fetch,
          #choose and #transcribe at module load and would go on writing to
          detached nodes. Same reason as the details panel below.
        */}
        <div
          id="source-row"
          /* display:contents when open, so the four controls keep wrapping as
             direct children of the header's flex row and the open layout is
             byte-for-byte what it was before the wrapper existed. */
          className={layout.sourceOpen ? 'contents' : 'hidden'}
        >
          <input
            id="url"
            type="url"
            placeholder="…or paste a video URL"
            spellCheck={false}
            className="min-w-0 max-w-[260px] flex-[1_1_200px] rounded-full border border-line bg-white px-3.5 py-2 text-[13px] text-ink focus:outline-2 focus:-outline-offset-1 focus:outline-accent/35"
          />
          <button id="fetch" type="button" className="lecture-btn">
            Fetch
          </button>
          <button id="choose" type="button" className="lecture-btn">
            Choose video…
          </button>
          <button id="transcribe" type="button" disabled className="lecture-btn lecture-btn--primary">
            Transcribe
          </button>
        </div>

        <button
          type="button"
          className="lecture-btn"
          aria-expanded={layout.sourceOpen}
          aria-controls="source-row"
          onClick={() => setLayout((v) => ({ ...v, sourceOpen: !v.sourceOpen }))}
        >
          Source
          <span
            aria-hidden="true"
            className={`ml-1.5 inline-block text-[9px] transition-transform duration-200 ease-signer ${layout.sourceOpen ? 'rotate-180' : ''}`}
          >
            ▾
          </span>
        </button>

        <button
          ref={triggerRef}
          type="button"
          className="lecture-btn"
          aria-expanded={detailsOpen}
          aria-controls="details-panel"
          onClick={(e) => {
            // Without this the document listener above sees the same click and
            // closes the panel the moment it opens.
            e.stopPropagation();
            setDetailsOpen((v) => !v);
          }}
        >
          Details
          <span
            aria-hidden="true"
            className={`ml-1.5 inline-block text-[9px] transition-transform duration-200 ease-signer ${detailsOpen ? 'rotate-180' : ''}`}
          >
            ▾
          </span>
        </button>

        {/*
          Always mounted — see the note at the top. Hidden with a class so
          main.ts keeps its references.
        */}
        <div
          id="details-panel"
          ref={panelRef}
          role="region"
          aria-label="Run details"
          className={`absolute top-full right-[18px] z-40 mt-2 max-h-[min(70vh,520px)] w-[min(320px,calc(100vw-36px))] overflow-auto rounded-xl border border-line bg-white p-3.5 text-[13px] shadow-[0_14px_36px_-12px_rgba(22,19,15,0.26)] max-[560px]:right-[18px] max-[560px]:left-[18px] max-[560px]:w-auto ${detailsOpen ? '' : 'hidden'}`}
        >
          <h2 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-soft">
            Run
          </h2>
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-1">
            <dt className="text-muted-soft">file</dt>
            <dd id="m-file" className="m-0 min-w-0 break-words">–</dd>
            <dt className="text-muted-soft">language</dt>
            <dd id="m-lang" className="m-0">–</dd>
            <dt className="text-muted-soft">duration</dt>
            <dd id="m-dur" className="m-0">–</dd>
            <dt className="text-muted-soft">segments</dt>
            <dd id="m-segs" className="m-0">–</dd>
            <dt className="text-muted-soft">signable</dt>
            <dd id="m-cov" className="m-0">–</dd>
            <dt className="text-muted-soft">model</dt>
            <dd id="m-model" className="m-0 min-w-0 break-words">–</dd>
          </dl>
          {/* display is flipped to block by main.ts once a still is found. */}
          <img
            id="lecturer"
            alt="Still of the lecturer detected in the video"
            className="mt-2.5 hidden w-full rounded-lg border border-line"
          />
          {/* Licence of a fetched video. Shown because this pipeline reuses a
              person's likeness, so the terms it arrived under are worth reading. */}
          <div id="source" className="source-panel" />
          <p id="m-note" className="mt-2 text-[12.5px] text-muted-soft empty:mt-0" />
        </div>
      </header>

      {/* Video and avatar side by side: the lecturer speaking, and the signing
          of what they said, so the two can be compared at a glance. The split
          between them is draggable — how much room each deserves depends on
          what you are checking, and that changes minute to minute. */}
      <div
        ref={stageRef}
        className="grid min-h-0 min-w-0"
        style={
          stacked
            ? { gridTemplateRows: `${layout.split}fr auto ${1 - layout.split}fr` }
            : { gridTemplateColumns: `${layout.split}fr auto ${1 - layout.split}fr` }
        }
      >
        <div className="relative min-h-0 min-w-0 overflow-hidden">
          <span className="pane-label">lecturer</span>
          <video id="video" controls playsInline className="h-full w-full bg-[#0d0b09] object-contain" />
        </div>

        <Splitter
          orientation={stacked ? 'horizontal' : 'vertical'}
          onDrag={dragSplit}
          onNudge={(d) =>
            setLayout((l) => ({
              ...l,
              split: Math.min(1 - MIN_SPLIT, Math.max(MIN_SPLIT, l.split + d * 0.02)),
            }))
          }
          onReset={() => setLayout((l) => ({ ...l, split: DEFAULT_SPLIT }))}
          valueNow={layout.split * 100}
          label="Resize lecturer and signing panes"
        />

        <div className="relative min-h-0 min-w-0 overflow-hidden">
          <span className="pane-label">signing</span>
          <div id="avatar" className="absolute inset-0" />
          {/*
            Above the head, matching the other two pipelines — it used to sit at
            the bottom of this pane, where it covered the avatar's feet. The
            camera reserves this band (see frameCamera in lecture/main.ts), so
            the two cannot collide however the pane is resized.

            px-3 keeps the box off the pane edges once the splitter makes this
            pane narrow.
          */}
          <div className="caption pointer-events-none absolute top-3 right-0 left-0 z-[6] flex justify-center px-3 opacity-0 transition-opacity duration-[250ms] ease-signer data-[state=active]:opacity-100">
            <div className="max-w-full rounded-xl bg-accent px-5 pt-2 pb-[7px] text-center text-white shadow-[0_8px_24px_rgba(22,19,15,0.16)]">
              {/* Sized off both axes: this pane is resizable, so its height is
                  not something the type can afford to ignore. */}
              <div id="caption" className="text-[clamp(0.95rem,min(2.2vw,3.2vh),1.5rem)] leading-tight font-bold" />
              <div id="gloss" className="text-[10px] uppercase tracking-[0.16em] opacity-75" />
            </div>
          </div>
        </div>
      </div>

      <Splitter
        orientation="horizontal"
        onDrag={dragTranscript}
        onNudge={(d) =>
          setLayout((l) => ({ ...l, transcript: clampTranscript(l.transcript - d * 16) }))
        }
        onReset={() => setLayout((l) => ({ ...l, transcript: DEFAULT_TRANSCRIPT }))}
        valueNow={
          pageRef.current ? (layout.transcript / pageRef.current.clientHeight) * 100 : 0
        }
        label="Resize transcript"
      />

      {/* The transcript doubles as the coverage report: every segment is shown,
          and the ones with no sign are visibly the majority. That gap is the
          honest state of the system and should not be hidden — which is why
          this, and not the run panel, is what gets the persistent space. Its
          height comes from the grid row above, so it is dragged rather than
          fixed. */}
      <div id="transcript" className="min-h-0 overflow-auto py-1.5">
        <p className="px-4 py-2 text-[12.5px] text-muted-soft">
          Choose a video and transcribe it. The avatar signs each phrase as the lecturer reaches
          it.
        </p>
      </div>
    </div>
  );
}
