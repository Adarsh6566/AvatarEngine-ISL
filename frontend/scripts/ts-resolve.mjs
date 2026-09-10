/**
 * Let Node resolve the extensionless relative imports the app is written with.
 *
 * Vite rewrites `./armIK` to `./armIK.ts` at build time; Node does not, and
 * without this every direct run of a source file dies on the first import. Used
 * by `npm test`, which runs the TypeScript through Node's own type stripping so
 * the suite needs no bundler and no test framework.
 */
import { registerHooks } from 'node:module';
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && !/\.[a-z]+$/i.test(specifier)) {
      const base = fileURLToPath(new URL(specifier, context.parentURL));
      for (const ext of ['.ts', '.tsx', '.js']) {
        if (existsSync(base + ext)) {
          return { url: pathToFileURL(base + ext).href, shortCircuit: true };
        }
      }
    }
    return nextResolve(specifier, context);
  },
});
