/**
 * G1 regression: the floating "tailoring" notice must STAY minimized across navigation.
 * Minimized (+ the one-shot reveal) live in the store — a module singleton that survives
 * the notice's per-route remount — not in component-local state that would reset.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { useGenerationStore } from '@/stores/useGenerationStore';

describe('useGenerationStore — minimized persistence (G1)', () => {
  beforeEach(() => useGenerationStore.getState().clear());

  it('defaults to expanded (not minimized) and no reveal', () => {
    const s = useGenerationStore.getState();
    expect(s.minimized).toBe(false);
    expect(s.revealed).toBe(false);
  });

  it('keeps minimized set — it does not reset (survives a component remount)', () => {
    useGenerationStore.getState().setMinimized(true);
    // A remount would read the store again; the value is still true.
    expect(useGenerationStore.getState().minimized).toBe(true);
  });

  it('a new run resets minimized + revealed to fresh (expanded again)', () => {
    useGenerationStore.getState().setMinimized(true);
    useGenerationStore.getState().setRevealed(true);
    useGenerationStore.getState().setPending({ syncId: 's1', staged: 3 });
    const s = useGenerationStore.getState();
    expect(s.minimized).toBe(false);
    expect(s.revealed).toBe(false);
    expect(s.pending).toEqual({ syncId: 's1', staged: 3 });
  });

  it('clear() resets everything', () => {
    useGenerationStore.getState().setPending({ syncId: 's1', staged: 3 });
    useGenerationStore.getState().setMinimized(true);
    useGenerationStore.getState().clear();
    const s = useGenerationStore.getState();
    expect(s.pending).toBeNull();
    expect(s.minimized).toBe(false);
    expect(s.revealed).toBe(false);
  });
});
