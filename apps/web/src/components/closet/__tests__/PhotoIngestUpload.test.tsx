/**
 * PhotoIngestUpload — Wave 1.5 state machine (pick → detect → select → commit).
 *
 * The api module is mocked at the boundary (like review.test.tsx): detect returns
 * canned sessions, commit resolves a run id, and the assertions pin the EXACT
 * selections payload the component hands to commitPhotoIngest.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import type { PhotoDetectSession, PhotoRegion } from '@/lib/api/gmail';

// jsdom lacks PointerEvent/ResizeObserver (RegionSelector renders in the select step).
if (typeof window !== 'undefined' && !window.PointerEvent) {
  window.PointerEvent = window.MouseEvent as unknown as typeof PointerEvent;
}
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

const invalidate = vi.fn();
vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: Object.assign(vi.fn(), { getState: () => ({ invalidate }) }),
}));

const detectPhotoIngest = vi.fn();
const commitPhotoIngest = vi.fn();
vi.mock('@/lib/api/gmail', () => {
  class PhotoSessionExpiredError extends Error {}
  return {
    detectPhotoIngest: (...args: unknown[]) => detectPhotoIngest(...args),
    commitPhotoIngest: (...args: unknown[]) => commitPhotoIngest(...args),
    PhotoSessionExpiredError,
  };
});

import { PhotoIngestUpload } from '../PhotoIngestUpload';
import { usePhotoPickStore } from '@/stores/usePhotoPickStore';

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
    regions: [region(1, 'T-shirt', [100, 100, 900, 900]), region(2, 'Sneakers', [600, 600, 850, 850])],
    ...over,
  };
}

const dupSession = (): PhotoDetectSession =>
  session({ session_id: null, duplicate: true, regions: [] });

const jpeg = (name: string) => new File(['x'], name, { type: 'image/jpeg' });

/** Feed files through the (first) hidden gallery input. */
function pickFiles(files: File[]) {
  const input = document.querySelector('input[type="file"]');
  expect(input).not.toBeNull();
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  fireEvent.change(input!);
}

beforeEach(() => {
  vi.clearAllMocks();
  usePhotoPickStore.setState({ files: [] });
});

describe('PhotoIngestUpload', () => {
  it('detect reaches the select step; commit pushes /review with the exact selections payload', async () => {
    const file = jpeg('a.jpg');
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-9',
      images_processed: 1,
      staged: 2,
      duplicates: 0,
      held_multi_person: 0,
      message: null,
    });

    render(<PhotoIngestUpload />);
    pickFiles([file]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));

    // Select step: regions on screen, all selected.
    expect(await screen.findByRole('button', { name: 'Add 2 items' })).toBeEnabled();
    expect(detectPhotoIngest).toHaveBeenCalledWith([file]);

    fireEvent.click(screen.getByRole('button', { name: 'Add 2 items' }));

    await waitFor(() => expect(commitPhotoIngest).toHaveBeenCalledTimes(1));
    // SAME File objects + the JSON-able selections structure.
    expect(commitPhotoIngest).toHaveBeenCalledWith(
      [file],
      [{ session_id: 'sess-1', selected_region_ids: [1, 2], manual_boxes: [] }],
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith('/review?sync_id=run-9'));
    expect(invalidate).toHaveBeenCalled();
  });

  it('toggling a region off before commit changes the payload', async () => {
    const file = jpeg('a.jpg');
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-3',
      images_processed: 1,
      staged: 1,
      duplicates: 0,
      held_multi_person: 0,
      message: null,
    });

    render(<PhotoIngestUpload />);
    pickFiles([file]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));

    fireEvent.click(await screen.findByRole('button', { name: 'Sneakers region' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add 1 item' }));

    await waitFor(() =>
      expect(commitPhotoIngest).toHaveBeenCalledWith(
        [file],
        [{ session_id: 'sess-1', selected_region_ids: [1], manual_boxes: [] }],
      ),
    );
  });

  it('all-duplicate photos short-circuit back to pick with an "Already added" notice', async () => {
    detectPhotoIngest.mockResolvedValue({ sessions: [dupSession()] });

    render(<PhotoIngestUpload />);
    pickFiles([jpeg('dup.jpg')]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));

    expect(await screen.findByText(/already added/i)).toBeInTheDocument();
    // Back at pick with the queue cleared — no select step, no commit.
    expect(screen.getByRole('button', { name: 'Select photos to continue' })).toBeDisabled();
    expect(commitPhotoIngest).not.toHaveBeenCalled();
  });

  it('consumes the AddItemDrawer handoff store on mount and jumps straight to detect', async () => {
    const file = jpeg('handoff.jpg');
    usePhotoPickStore.setState({ files: [file] });
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });

    render(<PhotoIngestUpload />);

    expect(await screen.findByRole('button', { name: 'Add 2 items' })).toBeInTheDocument();
    expect(detectPhotoIngest).toHaveBeenCalledWith([file]);
    // One-shot handoff: the store is drained.
    expect(usePhotoPickStore.getState().files).toHaveLength(0);
  });

  it('commit that stages nothing resets to pick and surfaces the server message', async () => {
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-0',
      images_processed: 1,
      staged: 0,
      duplicates: 0,
      held_multi_person: 1,
      message: 'Held for review — more than one person in the photo.',
    });

    render(<PhotoIngestUpload />);
    pickFiles([jpeg('a.jpg')]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Add 2 items' }));

    expect(await screen.findByText(/held for review/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Select photos to continue' })).toBeDisabled();
  });

  it('detect failure surfaces the error and stays recoverable at pick', async () => {
    detectPhotoIngest.mockRejectedValue(new Error('Could not reach the scanner.'));

    render(<PhotoIngestUpload />);
    pickFiles([jpeg('a.jpg')]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));

    expect(await screen.findByText('Could not reach the scanner.')).toBeInTheDocument();
    // Files stay picked so the user can just retry.
    expect(screen.getByRole('button', { name: 'Find clothes in 1 photo' })).toBeEnabled();
  });
});
