/**
 * RegionSelector — the Wave 1.5 region-selection step.
 *
 * jsdom has no layout, so geometry is stubbed: getBoundingClientRect is mocked to a
 * 400×400 frame and the sessions use 1000×1000 photos, giving a 1:1 displayed rect
 * at (0,0) with scale 0.4 — so drawn-pixel → 0..1000 conversion is exactly ×2.5.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { RegionSelector } from '../RegionSelector';
import type { PhotoDetectSession, PhotoRegion } from '@/lib/api/gmail';

// jsdom lacks PointerEvent; MouseEvent carries the clientX/clientY the draw layer
// reads, and React's onPointer* handlers key off the event TYPE, not the class.
if (typeof window !== 'undefined' && !window.PointerEvent) {
  window.PointerEvent = window.MouseEvent as unknown as typeof PointerEvent;
}

// jsdom lacks ResizeObserver; the component falls back to a resize listener, but a
// quiet stub keeps the primary path deterministic.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

const RECT = {
  x: 0, y: 0, top: 0, left: 0, right: 400, bottom: 400,
  width: 400, height: 400,
  toJSON: () => ({}),
} as DOMRect;

let rectSpy: { mockRestore: () => void };

beforeEach(() => {
  rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(RECT);
});

afterEach(() => {
  rectSpy.mockRestore();
});

function region(region_id: number, name: string, box_2d: [number, number, number, number]): PhotoRegion {
  return {
    region_id,
    box_2d,
    name,
    category: 'top',
    color: null,
    pattern: null,
    material: null,
    fit: null,
    brand: null,
    confidence_overall: 0.9,
    confidence: {},
  };
}

function session(over: Partial<PhotoDetectSession> = {}): PhotoDetectSession {
  return {
    session_id: 'sess-1',
    filename: 'a.jpg',
    image_sha256: 'sha-a',
    width: 1000,
    height: 1000,
    duplicate: false,
    person_count: 1,
    regions: [
      region(1, 'T-shirt', [100, 100, 900, 900]), // big box
      region(2, 'Sneakers', [600, 600, 850, 850]), // small box, overlaps the big one
    ],
    ...over,
  };
}

const dupSession = (): PhotoDetectSession =>
  session({ session_id: null, filename: 'dup.jpg', image_sha256: 'sha-dup', duplicate: true, regions: [] });

function renderSelector(
  photos: { previewUrl: string; session: PhotoDetectSession }[],
  onCommit = vi.fn(),
  onCancel = vi.fn(),
) {
  render(<RegionSelector photos={photos} onCommit={onCommit} onCancel={onCancel} />);
  return { onCommit, onCancel };
}

/** Drag on the draw layer: pointerdown → move → up (MouseEvents typed as pointer). */
function drag(el: Element, from: { x: number; y: number }, to: { x: number; y: number }) {
  fireEvent.pointerDown(el, { clientX: from.x, clientY: from.y });
  fireEvent.pointerMove(el, { clientX: to.x, clientY: to.y });
  fireEvent.pointerUp(el, { clientX: to.x, clientY: to.y });
}

describe('RegionSelector', () => {
  it('renders every detected region selected by default, with the footer count', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);

    const tshirt = screen.getByRole('button', { name: 'T-shirt region' });
    const sneakers = screen.getByRole('button', { name: 'Sneakers region' });
    expect(tshirt).toHaveAttribute('aria-pressed', 'true');
    expect(sneakers).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Add 2 items' })).toBeEnabled();
  });

  it('stacks the smaller box above the bigger one so it wins overlapping taps', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);
    // The region toggle now fills a positioned wrapper that carries the z-index.
    const tshirt = screen.getByRole('button', { name: 'T-shirt region' }).parentElement!;
    const sneakers = screen.getByRole('button', { name: 'Sneakers region' }).parentElement!;
    expect(Number(sneakers.style.zIndex)).toBeGreaterThan(Number(tshirt.style.zIndex));
  });

  it('tap toggles a region and the footer count follows', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);

    const tshirt = screen.getByRole('button', { name: 'T-shirt region' });
    fireEvent.click(tshirt);
    expect(tshirt).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Add 1 item' })).toBeEnabled();

    // Toggle the other off too → 0 selected disables the commit CTA.
    fireEvent.click(screen.getByRole('button', { name: 'Sneakers region' }));
    expect(screen.getByRole('button', { name: 'Add 0 items' })).toBeDisabled();

    // Toggle back on.
    fireEvent.click(tshirt);
    expect(tshirt).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Add 1 item' })).toBeEnabled();
  });

  it('draw mode adds a manual box (selected + counted) that is removable', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);

    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    expect(screen.getByText('Drag around the item')).toBeInTheDocument();

    drag(screen.getByTestId('draw-layer'), { x: 40, y: 40 }, { x: 240, y: 140 });

    // New manual box: carries a name input, auto-selected (counted), draw mode auto-exits.
    expect(screen.getByPlaceholderText('Name (optional)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add 3 items' })).toBeEnabled();
    expect(screen.queryByTestId('draw-layer')).toBeNull();

    // × deletes it and the count drops back.
    fireEvent.click(screen.getByRole('button', { name: 'Remove drawn item' }));
    expect(screen.queryByPlaceholderText('Name (optional)')).toBeNull();
    expect(screen.getByRole('button', { name: 'Add 2 items' })).toBeEnabled();
  });

  it('names a drawn box via its inline input', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    drag(screen.getByTestId('draw-layer'), { x: 40, y: 40 }, { x: 240, y: 140 });

    const input = screen.getByPlaceholderText('Name (optional)') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Scarf' } });
    expect(input.value).toBe('Scarf');
  });

  it('"adjust" converts a detected box into an editable manual box (count preserved)', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);

    // Adjust the T-shirt: its detected toggle disappears, replaced by a manual box
    // pre-named from the detection; the overall count is unchanged (deselect + add).
    fireEvent.click(screen.getByRole('button', { name: 'Adjust T-shirt box' }));
    expect(screen.queryByRole('button', { name: 'T-shirt region' })).toBeNull();
    expect((screen.getByPlaceholderText('Name (optional)') as HTMLInputElement).value).toBe('T-shirt');
    expect(screen.getByRole('button', { name: 'Add 2 items' })).toBeEnabled();
  });

  it('discards a drag smaller than ~4% of the image per dimension', () => {
    renderSelector([{ previewUrl: 'blob:a', session: session() }]);

    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    // 4% of 400px = 16px minimum; an 8px nudge must be thrown away.
    drag(screen.getByTestId('draw-layer'), { x: 50, y: 50 }, { x: 58, y: 58 });

    expect(screen.queryByPlaceholderText('Name (optional)')).toBeNull();
    expect(screen.getByRole('button', { name: 'Add 2 items' })).toBeEnabled();
    // Draw mode stays armed for another try.
    expect(screen.getByTestId('draw-layer')).toBeInTheDocument();
  });

  it('shows duplicates as skipped tiles and steps between photos', () => {
    renderSelector([
      { previewUrl: 'blob:dup', session: dupSession() },
      { previewUrl: 'blob:a', session: session() },
    ]);

    // Opens on the first selectable photo (index 1), duplicates count nothing.
    expect(screen.getByText('Photo 2 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add 2 items' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Previous photo' }));
    expect(screen.getByText('Photo 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('Already added')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /region$/ })).toBeNull();
    // No drawing on a duplicate either.
    expect(screen.getByRole('button', { name: 'Add item' })).toBeDisabled();
  });

  it('commits only live sessions with the toggled ids and drawn 0..1000 boxes', () => {
    const { onCommit } = renderSelector([
      { previewUrl: 'blob:dup', session: dupSession() },
      { previewUrl: 'blob:a', session: session() },
    ]);

    // On photo 2 (the live one): drop Sneakers, draw one manual box.
    fireEvent.click(screen.getByRole('button', { name: 'Sneakers region' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    // 400×400 layer → ×2.5 into 0..1000: (40,40)-(240,140) → [100,100,350,600].
    drag(screen.getByTestId('draw-layer'), { x: 40, y: 40 }, { x: 240, y: 140 });

    fireEvent.click(screen.getByRole('button', { name: 'Add 2 items' }));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith([
      {
        session_id: 'sess-1',
        selected_region_ids: [1],
        manual_boxes: [[100, 100, 350, 600]],
      },
    ]);
  });

  it('Cancel hands control back', () => {
    const { onCancel } = renderSelector([{ previewUrl: 'blob:a', session: session() }]);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
