import { createRoot } from 'react-dom/client';
import './styles/theme.css';
import { IndexApp } from './IndexApp';

/** No StrictMode — see signer/entry.tsx for why. */
const root = document.getElementById('root');
if (!root) throw new Error('Mount element #root not found');
createRoot(root).render(<IndexApp />);
