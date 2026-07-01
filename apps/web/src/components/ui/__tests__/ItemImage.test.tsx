import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ItemImage } from '@/components/ui/ItemImage';

describe('ItemImage', () => {
  it('renders the <img> with the given src, visible and absolute-filling (not collapsible)', () => {
    render(
      // A sized, positioned parent — the contract ItemImage expects.
      <div style={{ position: 'relative', width: 200, height: 300 }}>
        <ItemImage src="https://example.com/cutout.jpg" alt="Blue Tee" fit="contain" />
      </div>,
    );

    const img = screen.getByRole('img', { name: 'Blue Tee' });
    // Points straight at the URL — no blob / object-URL indirection.
    expect(img).toHaveAttribute('src', 'https://example.com/cutout.jpg');
    // Never gated hidden: no display:none, no visibility:hidden, no hidden attr.
    expect(img).toBeVisible();
    // Fills its box by absolute positioning (immune to h-full percentage collapse).
    expect(img.className).toContain('absolute');
    expect(img.className).toContain('inset-0');
    expect(img.className).toContain('object-contain');
  });

  it('shows the neutral empty label and no <img> when src is null', () => {
    render(<ItemImage src={null} alt="none" emptyLabel="No image" />);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('No image')).toBeInTheDocument();
  });
});
