import { useEffect, useRef } from 'react';

/**
 * Chrome for the CAPTURED-MOTION signer, as React + Tailwind.
 *
 * This component owns the MARKUP and nothing else. The avatar, the retargeting
 * and the sign queue stay in signer/main.ts, which is 460 lines of imperative
 * three.js that React has no opinion about and no way to improve — a WebGL
 * canvas is not something a render tree can describe.
 *
 * So the division is: React paints the chrome, then hands over. main.ts is
 * imported for its side effects once the DOM it expects exists, and drives
 * these elements directly from there.
 *
 * That is why the ids below are load-bearing rather than decorative, and why
 * this component holds no state: main.ts writes to #caption, #gloss and #status
 * imperatively, and frameCamera() MEASURES .bar and .caption to fit the avatar
 * into the space the floating chrome leaves free. A re-render that replaced
 * those nodes would break both. Nothing here changes after mount, so nothing
 * does.
 */
export function SignerApp() {
  const started = useRef(false);

  useEffect(() => {
    // React 19 StrictMode invokes effects twice in development. The ES module
    // cache makes a second import a no-op, but the guard states the intent
    // rather than relying on that.
    if (started.current) return;
    started.current = true;
    void import('./main');
  }, []);

  return (
    <>
      {/* The canvas mounts here. main.ts looks this up by id. */}
      <div id="app" className="fixed inset-0" />

      <div className="badge fixed top-4 left-[18px] z-30 text-[11px] uppercase tracking-[0.14em] text-ink/40">
        captured motion · no .vrma
      </div>

      {/* data-state is toggled by setCaption() in main.ts. */}
      <div className="caption pointer-events-none fixed top-0 right-0 left-0 z-20 flex -translate-y-2.5 justify-center px-5 pt-6 opacity-0 transition-[opacity,transform] duration-300 ease-signer data-[state=active]:translate-y-0 data-[state=active]:opacity-100">
        <div className="rounded-[14px] bg-accent px-[26px] pt-3 pb-2.5 text-center text-white shadow-[0_8px_24px_rgba(22,19,15,0.16)]">
          <div id="caption" className="text-[34px] leading-tight font-bold tracking-[-0.01em]" />
          <div id="gloss" className="mt-0.5 text-[11px] uppercase tracking-[0.16em] opacity-75" />
        </div>
      </div>

      <div className="bar fixed bottom-[26px] left-1/2 z-30 w-[min(620px,calc(100vw-40px))] -translate-x-1/2">
        <div className="flex items-center gap-2 rounded-full border border-ink/10 bg-white py-2 pr-2 pl-[22px] shadow-[0_10px_30px_rgba(22,19,15,0.1)]">
          <input
            id="text"
            type="text"
            placeholder="Type a sign…"
            autoComplete="off"
            spellCheck={false}
            /* min-w-0: a flex item defaults to min-width:auto and an input's
               intrinsic width is wide, so without this the field refuses to
               shrink and pushes Sign off the right edge of a phone. */
            className="min-w-0 flex-1 border-0 bg-transparent py-2 text-[17px] text-ink outline-0 placeholder:text-ink/40"
          />
          <button
            id="mic"
            type="button"
            title="Sign what you say"
            aria-label="Sign what you say"
            className="flex h-10 w-10 flex-none cursor-pointer items-center justify-center rounded-full border border-ink/10 bg-transparent text-ink/55 transition-[background-color,color,border-color] duration-200 ease-signer hover:bg-ink/5 hover:text-ink disabled:cursor-default disabled:opacity-35 data-[listening=true]:animate-[mic-pulse_1.6s_ease-in-out_infinite] data-[listening=true]:border-accent data-[listening=true]:bg-accent data-[listening=true]:text-white motion-reduce:data-[listening=true]:animate-none"
          >
            <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
              <path
                d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Z M19 11a7 7 0 0 1-14 0 M12 18v3"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            id="sign"
            type="button"
            className="flex-none cursor-pointer rounded-full border-0 bg-accent px-[26px] py-[11px] font-semibold text-white transition-opacity duration-200 ease-signer disabled:cursor-default disabled:opacity-45"
          >
            Sign
          </button>
        </div>

        {/* pr-[92px] under 820px reserves the speed control's footprint, which
            is fixed bottom-right and would otherwise sit on top of this text. */}
        <div className="mt-2.5 text-center text-[12.5px] text-ink/50 max-[820px]:pr-[92px]">
          <div id="status" className="min-h-[18px] text-accent" />
          <div>
            knows: <b className="font-semibold text-ink/70"><span id="known" /></b>
          </div>
        </div>
      </div>
    </>
  );
}
