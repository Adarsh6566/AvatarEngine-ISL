import { useEffect, useRef } from 'react';

/**
 * Shell for the .vrma pipeline.
 *
 * This page has almost no markup of its own: its chrome — the input bar and the
 * fingerspelling caption — is built by SignControls and SignCaption, which
 * append themselves to document.body and are driven imperatively by main.ts
 * (showMessage, setEnabled, focus). They are framework-agnostic widgets, the
 * same as PlaybackSpeedControl and ActivityIndicator, so they are left as they
 * are and their styles live in theme.css rather than in JSX.
 *
 * What React contributes here is the mount point, the stylesheet import and one
 * consistent entry shape across all three pipelines.
 */
export function IndexApp() {
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void import('./main');
  }, []);

  return <div id="app" className="fixed inset-0" />;
}
