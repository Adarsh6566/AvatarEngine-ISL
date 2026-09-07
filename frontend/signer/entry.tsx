import { createRoot } from 'react-dom/client';
import '../styles/theme.css';
import { SignerApp } from './SignerApp';

/**
 * React entry for the captured-motion signer.
 *
 * No StrictMode. It double-invokes effects in development, and the effect here
 * imports a module whose side effect is building a WebGL scene — running that
 * twice is not something the module was written to survive, and the second run
 * would be measuring a canvas the first already owns.
 */
const root = document.getElementById('root');
if (!root) throw new Error('Mount element #root not found');
createRoot(root).render(<SignerApp />);
