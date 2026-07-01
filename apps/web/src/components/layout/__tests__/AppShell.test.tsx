import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';

import { AppShell } from '@/components/layout/AppShell';

describe('AppShell backdrop stacking', () => {
  it('backdrop layers are non-interactive and transform-free (cannot win hit-testing)', () => {
    const { container } = render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    // The decorative backdrop layers (photo + scrim) are aria-hidden fixed divs.
    const layers = Array.from(container.querySelectorAll('[aria-hidden]')) as HTMLElement[];
    expect(layers.length).toBeGreaterThanOrEqual(2);

    for (const el of layers) {
      // Must not capture pointer events (kills elementFromPoint capturing the backdrop).
      expect(el.className).toContain('pointer-events-none');
      // Must NOT be centered with a transform (that creates its own stacking context /
      // compositing layer and breaks z-index vs. the z-10 content).
      expect(el.className).not.toContain('-translate-x-1/2');
      // Transform-free centering instead.
      expect(el.className).toContain('mx-auto');
      // Painted behind content.
      expect(el.className).toContain('z-0');
    }

    // The content wrapper sits above the backdrop in its own stacking context.
    const content = container.querySelector('.z-10');
    expect(content).not.toBeNull();
  });
});
