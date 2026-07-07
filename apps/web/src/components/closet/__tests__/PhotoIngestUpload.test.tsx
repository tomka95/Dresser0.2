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
const getIngestStatus = vi.fn();
vi.mock('@/lib/api/gmail', () => {
  class PhotoSessionExpiredError extends Error {}
  return {
    detectPhotoIngest: (...args: unknown[]) => detectPhotoIngest(...args),
    commitPhotoIngest: (...args: unknown[]) => commitPhotoIngest(...args),
    getIngestStatus: (...args: unknown[]) => getIngestStatus(...args),
    PhotoSessionExpiredError,
  };
});

// HEIC decoder is mocked (no wasm): looksLikeHeic keys off name/type, and transcode
// returns a deterministic JPEG File so tests can assert the SAME bytes flow onward.
// The error class is declared INSIDE the factory (it's referenced at mock-eval time,
// so a module-level class would hit the TDZ under ESM import hoisting).
const looksLikeHeic = vi.fn(
  (f: File) => /\.heic$/i.test(f.name) || (f.type || '').includes('heic'),
);
const transcodeHeicToJpeg = vi.fn(
  async (f: File) => new File(['jpeg-bytes'], f.name.replace(/\.heic$/i, '.jpg'), { type: 'image/jpeg' }),
);
vi.mock('@/lib/image/heic', () => {
  class HeicTranscodeError extends Error {}
  return {
    looksLikeHeic: (...args: unknown[]) => looksLikeHeic(...(args as [File])),
    transcodeHeicToJpeg: (...args: unknown[]) => transcodeHeicToJpeg(...(args as [File])),
    HeicTranscodeError,
  };
});

import { PhotoIngestUpload } from '../PhotoIngestUpload';
import { usePhotoPickStore } from '@/stores/usePhotoPickStore';
import { useGenerationStore } from '@/stores/useGenerationStore';
import { HeicTranscodeError } from '@/lib/image/heic'; // the mocked factory's class

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
  // Module-singleton store — reset so a prior test's pending run can't hijack the mount
  // (the resume effect would jump straight to the "preparing" pill).
  useGenerationStore.setState({ pending: null });
  // Default: a run still generating (the pill stays "Preparing …" until tapped).
  getIngestStatus.mockResolvedValue({
    sync_id: 'run',
    status: 'running',
    progress: {
      fetched: 0,
      filtered: 0,
      extracted: 0,
      total_estimate: null,
      generation_total: 2,
      generation_ready: 0,
      generation_failed: 0,
    },
    started_at: null,
    finished_at: null,
  });
});

describe('PhotoIngestUpload', () => {
  it('detect reaches the select step; commit shows the Preparing pill and routes to /review on tap', async () => {
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
    // Commit no longer force-navigates: a non-blocking "Tailoring" pill appears while the
    // product cards generate, and routes to the run-scoped deck when tapped.
    const pill = await screen.findByRole('button', { name: 'Tailoring 2 items' });
    expect(invalidate).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(pill);
    expect(push).toHaveBeenCalledWith('/review?sync_id=run-9');
  });

  it('auto-advances to /review when the run finishes while waiting on the preparing screen', async () => {
    const file = jpeg('a.jpg');
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-7', images_processed: 1, staged: 2, duplicates: 0,
      held_multi_person: 0, message: null,
    });
    // The run is already done on the first poll → the pill fires onDone → auto-advance.
    getIngestStatus.mockResolvedValue({
      sync_id: 'run-7', status: 'completed',
      progress: {
        fetched: 0, filtered: 0, extracted: 0, total_estimate: null,
        generation_total: 2, generation_ready: 2, generation_failed: 0,
      },
      started_at: null, finished_at: null,
    });

    render(<PhotoIngestUpload />);
    pickFiles([file]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Add 2 items' }));

    await waitFor(() => expect(commitPhotoIngest).toHaveBeenCalledTimes(1));
    // No tap: waiting on the screen auto-forwards to the run-scoped deck.
    await waitFor(() => expect(push).toHaveBeenCalledWith('/review?sync_id=run-7'));
  });

  it('"Tailor in the background" leaves for home and keeps the run pending for the notice', async () => {
    const file = jpeg('a.jpg');
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-5', images_processed: 1, staged: 2, duplicates: 0,
      held_multi_person: 0, message: null,
    });
    // Default status is 'running' (beforeEach) → no auto-advance.

    render(<PhotoIngestUpload />);
    pickFiles([file]);
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Add 2 items' }));

    const bg = await screen.findByRole('button', { name: 'Tailor in the background' });
    fireEvent.click(bg);
    expect(push).toHaveBeenCalledWith('/home');
    // The run stays stashed so the global notice can bring the user back when ready.
    expect(useGenerationStore.getState().pending).toEqual({ syncId: 'run-5', staged: 2 });
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
    // 'Snap a photo' is the pick-step camera source-card title (redesigned entry).
    expect(screen.getByText('Snap a photo')).toBeInTheDocument();
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
    // Reset to pick — the redesigned source cards are back on screen.
    expect(screen.getByText('Snap a photo')).toBeInTheDocument();
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

  it('transcodes a picked HEIC to JPEG and sends BYTE-IDENTICAL bytes to detect and commit', async () => {
    const heic = new File(['heic-bytes'], 'IMG.heic', { type: 'image/heic' });
    detectPhotoIngest.mockResolvedValue({ sessions: [session()] });
    commitPhotoIngest.mockResolvedValue({
      sync_id: 'run-h',
      images_processed: 1,
      staged: 2,
      duplicates: 0,
      held_multi_person: 0,
      message: null,
    });

    render(<PhotoIngestUpload />);
    pickFiles([heic]);

    // addFiles transcodes (async) before the CTA reflects the picked photo.
    fireEvent.click(await screen.findByRole('button', { name: 'Find clothes in 1 photo' }));
    expect(await screen.findByRole('button', { name: 'Add 2 items' })).toBeEnabled();

    expect(transcodeHeicToJpeg).toHaveBeenCalledTimes(1); // transcoded ONCE
    const detectFile = (detectPhotoIngest.mock.calls[0][0] as File[])[0];
    expect(detectFile.type).toBe('image/jpeg'); // not the original HEIC
    expect(detectFile.name).toBe('IMG.jpg');

    fireEvent.click(screen.getByRole('button', { name: 'Add 2 items' }));
    await waitFor(() => expect(commitPhotoIngest).toHaveBeenCalledTimes(1));

    const commitFile = (commitPhotoIngest.mock.calls[0][0] as File[])[0];
    // The exact same transcoded File object reaches both endpoints — identical bytes,
    // so the server's sha256 detect→commit rebind holds.
    expect(commitFile).toBe(detectFile);
  });

  it('surfaces a clear error when HEIC transcode fails, staying at pick', async () => {
    transcodeHeicToJpeg.mockRejectedValueOnce(
      new HeicTranscodeError("We couldn't read that HEIC photo."),
    );

    render(<PhotoIngestUpload />);
    pickFiles([new File(['x'], 'broken.heic', { type: 'image/heic' })]);

    expect(await screen.findByText(/couldn't read that heic/i)).toBeInTheDocument();
    // Nothing picked, no detect — recoverable (still on the pick-step source cards).
    expect(screen.getByText('Snap a photo')).toBeInTheDocument();
    expect(detectPhotoIngest).not.toHaveBeenCalled();
  });
});
