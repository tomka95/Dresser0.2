import { describe, it, expect } from 'vitest';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/**
 * Centralization guard for the backend API base URL.
 *
 * After the api-base consolidation, exactly ONE module (src/lib/api/base.ts) is
 * allowed to name the dev-fallback host. Every other client imports API_BASE_URL
 * from it. This test walks the whole src tree and fails if the literal host:port
 * reappears anywhere else — so a new client can't silently hard-code its own base
 * and re-break the deployed / Capacitor builds.
 *
 * The needle is assembled from parts so THIS guard file never contains the
 * contiguous literal (which would otherwise flag itself).
 */

// The single module permitted to spell out the dev fallback.
const ALLOWED = join('lib', 'api', 'base.ts');

// Locate apps/web/src regardless of whether vitest runs from apps/web or the
// repo root (import.meta.url is virtualized under vitest, so derive from cwd).
function resolveSrcDir(): string {
  const candidates = [join(process.cwd(), 'src'), join(process.cwd(), 'apps', 'web', 'src')];
  const found = candidates.find((c) => existsSync(join(c, ALLOWED)));
  if (!found) throw new Error('could not locate apps/web/src from ' + process.cwd());
  return found;
}
const SRC_DIR = resolveSrcDir();

// Assembled so this file itself is clean.
const NEEDLE = 'localhost' + ':8000';

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === 'node_modules' || entry === '.next') continue;
      walk(full, out);
    } else if (/\.(ts|tsx|js|jsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

describe('API base URL is centralized', () => {
  it(`has no hard-coded "${NEEDLE}" outside src/${ALLOWED.split(sep).join('/')}`, () => {
    const offenders = walk(SRC_DIR)
      .filter((f) => relative(SRC_DIR, f) !== ALLOWED)
      .filter((f) => readFileSync(f, 'utf8').includes(NEEDLE))
      .map((f) => relative(SRC_DIR, f).split(sep).join('/'));

    expect(offenders, `hard-coded base URL found in: ${offenders.join(', ')}`).toEqual([]);
  });

  it('the shared module is the one place that defines the fallback', () => {
    const base = readFileSync(join(SRC_DIR, ALLOWED), 'utf8');
    expect(base).toContain(NEEDLE);
    expect(base).toContain('NEXT_PUBLIC_API_URL');
  });
});
