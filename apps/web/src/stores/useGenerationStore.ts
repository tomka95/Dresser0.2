import { create } from 'zustand';

/**
 * useGenerationStore — the one in-progress photo-generation run the user can be
 * "notified" about (Wave 2).
 *
 * After a photo commit the backend generates a verified product card per garment in
 * the background. Two surfaces bring the user back to that run's review deck when it's
 * ready, both driven by this store + a GenerationProgressPill:
 *   1. the post-commit "preparing" screen (PhotoIngestUpload), and
 *   2. the in-deck "Tailor in the background" escape (/review) — which stashes the run
 *      here and routes away, so /add-photo can resurface the pill.
 *
 * In-memory only (a run id + a count); nothing persisted. Holds the LATEST run — a new
 * commit or a new escape overwrites it; reviewing/confirming clears it.
 */

export interface PendingGeneration {
  /**
   * The run to poll. `null` = provisional: the user backgrounded the flow while the commit
   * was still in flight (no sync_id yet), so the indicator can render INSTANTLY without a
   * run to poll. It's patched to the real id (via setPending) the moment commit resolves.
   */
  syncId: string | null;
  /** Candidates staged by the commit — the pill's initial denominator (an estimate while provisional). */
  staged: number;
}

type GenerationState = {
  pending: PendingGeneration | null;
  setPending: (pending: PendingGeneration) => void;
  clear: () => void;
};

export const useGenerationStore = create<GenerationState>((set) => ({
  pending: null,
  setPending(pending) {
    set({ pending });
  },
  clear() {
    set({ pending: null });
  },
}));
