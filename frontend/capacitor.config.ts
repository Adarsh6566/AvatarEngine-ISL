import type { CapacitorConfig } from '@capacitor/cli';

/**
 * Capacitor wraps the built site as an Android app.
 *
 * The whole reason this works is that `npm run build` emits a fully static
 * dist/ — no server process, no SSR step. Capacitor copies that directory into
 * an APK and serves it from a WebView, so the same three.js that runs in the
 * browser runs on the phone with no rewrite. It is also why Next.js was the
 * wrong choice here: it wants a Node server, and there is nowhere to run one
 * inside an APK.
 *
 * `webDir` is '../dist' because vite.config.ts already builds one level up
 * (build.outDir), keeping the built output out of frontend/.
 */
const config: CapacitorConfig = {
  appId: 'in.avatarengine.isl',
  appName: 'AvatarEngine ISL',
  webDir: '../dist',
  android: {
    // The avatar is the whole screen and the chrome floats over it; a light
    // background matches --color-paper so a slow first paint does not flash
    // black behind the canvas.
    backgroundColor: '#f2efe9',
  },
  server: {
    // Assets are bundled, so this only governs how the WebView labels its own
    // origin. https keeps it a secure context, which the mic on the signer page
    // requires — SpeechRecognition refuses to start on an insecure one.
    androidScheme: 'https',
  },
};

export default config;
