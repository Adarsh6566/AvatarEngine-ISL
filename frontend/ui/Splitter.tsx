import { useRef, useState } from 'react';

export interface SplitterProps {
  /**
   * Which way the divider LINE runs. 'vertical' is an upright line between two
   * side-by-side panes, dragged left and right; 'horizontal' is a lying-down
   * line between stacked panes, dragged up and down.
   */
  orientation: 'vertical' | 'horizontal';
  /** Pointer moved. The parent converts the position into its own units. */
  onDrag: (clientX: number, clientY: number) => void;
  /** Arrow key pressed: -1 towards the start, +1 towards the end. */
  onNudge: (direction: -1 | 1) => void;
  /** Double-click, or Home — put it back where it started. */
  onReset: () => void;
  /** 0-100, for assistive technology. */
  valueNow: number;
  label: string;
}

/**
 * A draggable divider between two panes.
 *
 * The visible line is 1px because a thick bar would be a permanent chrome tax
 * on a layout whose whole point is the two video panes. The HIT AREA is not
 * 1px — it is 11px, centred on the line via negative margins, because a
 * one-pixel drag target is unusable with a mouse and impossible with a finger.
 * The grid track stays 1px; the padding overhangs its neighbours harmlessly
 * since nothing there is interactive at the seam.
 *
 * Pointer events rather than mouse events, so a touch drag works with the same
 * code. setPointerCapture is what keeps the drag alive when the pointer crosses
 * the <video> or the WebGL canvas — without it those elements would swallow the
 * move events and the divider would stick.
 */
export function Splitter({ orientation, onDrag, onNudge, onReset, valueNow, label }: SplitterProps) {
  const dragging = useRef(false);
  const [active, setActive] = useState(false);
  const vertical = orientation === 'vertical';

  const begin = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    setActive(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    // A drag that selects the transcript text behind it feels broken, and the
    // cursor must not flicker back to default over the panes mid-drag.
    document.body.style.userSelect = 'none';
    document.body.style.cursor = vertical ? 'col-resize' : 'row-resize';
  };

  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    onDrag(e.clientX, e.clientY);
  };

  const end = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    dragging.current = false;
    setActive(false);
    e.currentTarget.releasePointerCapture(e.pointerId);
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  };

  const key = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const back = vertical ? 'ArrowLeft' : 'ArrowUp';
    const fwd = vertical ? 'ArrowRight' : 'ArrowDown';
    if (e.key === back) { e.preventDefault(); onNudge(-1); }
    else if (e.key === fwd) { e.preventDefault(); onNudge(1); }
    else if (e.key === 'Home') { e.preventDefault(); onReset(); }
  };

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={Math.round(valueNow)}
      aria-valuemin={0}
      aria-valuemax={100}
      tabIndex={0}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={onReset}
      onKeyDown={key}
      data-dragging={active}
      className={`splitter ${vertical ? 'splitter--vertical' : 'splitter--horizontal'}`}
    />
  );
}
