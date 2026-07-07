import { create } from 'zustand';
import type {
  Department,
  SizeProfile,
  FitPreferences,
  Archetype,
} from '@tailor/contracts';

import type {
  OnboardingSeedPayload,
  OnboardingPreference,
  OnboardingSignal,
} from '@/lib/api/onboarding';

/**
 * useOnboardingStore — staged answers for the 6-screen tap-only onboarding.
 *
 * Staged answers + the current step are DRAFT-PERSISTED to localStorage (key
 * `tailor.onboarding.progress`) so a refresh or accidental navigation mid-flow
 * never resets the user — on mount the flow rehydrates and (O9) offers a "pick up
 * where you left off" card. This is a client-only draft cache: it changes NOTHING
 * about commit semantics. The profile still commits ONCE via POST /onboarding/seed
 * (buildSeedPayload) at step-6 completion, and onboarding_completed_at is stamped
 * server-side ONLY on that success — so an abandoned draft never counts as
 * onboarded. The draft is cleared on reset() (successful seed OR "start over").
 *
 * The `completed` gate cache is NOT persisted here (it is a per-navigation
 * short-circuit for the status fetch, re-resolved from the server on a fresh load);
 * only the answer draft is written to storage.
 */

export const ONBOARDING_STEPS = 6;

/** localStorage key for the mid-flow answer draft (O9 resume). */
export const ONBOARDING_DRAFT_KEY = 'tailor.onboarding.progress';

/** One taste-deck swipe (screen 4). */
export interface TasteSwipe {
  archetype: Archetype;
  liked: boolean;
}

/** Coarse location captured on screen 6 (permission -> browser geolocation). */
export interface OnboardingLocation {
  lat: number;
  lon: number;
  timezone?: string;
}

interface OnboardingState {
  /** 1-indexed current step. */
  step: number;
  /** Whether the user is known to have completed onboarding (gate cache). */
  completed: boolean | null;
  /** True once hydrateDraft() has run (so the flow can wait before rendering). */
  hydrated: boolean;
  /**
   * Set at hydrate time: a mid-flow draft was found in storage (step > 1 or any
   * staged answer). Drives the O9 resume card; cleared once the user continues or
   * starts over.
   */
  resumable: boolean;

  // --- staged answers ------------------------------------------------------
  department?: Department;
  sizes: Partial<SizeProfile>;
  fits: Partial<FitPreferences>;
  tasteSwipes: TasteSwipe[];
  occasions: string[];
  location?: OnboardingLocation;

  // --- navigation ----------------------------------------------------------
  setStep: (step: number) => void;
  next: () => void;
  back: () => void;

  // --- draft persistence (O9) ----------------------------------------------
  /** Load any saved draft from localStorage; sets `hydrated` + `resumable`. */
  hydrateDraft: () => void;
  /** Dismiss the resume card without discarding the draft (user tapped Continue). */
  clearResumable: () => void;

  // --- per-screen setters --------------------------------------------------
  setDepartment: (d: Department) => void;
  setSize: <K extends keyof SizeProfile>(key: K, value: SizeProfile[K]) => void;
  setFit: <K extends keyof FitPreferences>(key: K, value: FitPreferences[K]) => void;
  addSwipe: (swipe: TasteSwipe) => void;
  toggleOccasion: (occasion: string) => void;
  setLocation: (location: OnboardingLocation) => void;

  setCompleted: (completed: boolean) => void;
  /** Clear staged answers (after a successful seed, or to restart). */
  reset: () => void;

  /** Map staged answers -> the single POST /onboarding/seed body. */
  buildSeedPayload: () => OnboardingSeedPayload;
}

const initialAnswers = {
  department: undefined as Department | undefined,
  sizes: {} as Partial<SizeProfile>,
  fits: {} as Partial<FitPreferences>,
  tasteSwipes: [] as TasteSwipe[],
  occasions: [] as string[],
  location: undefined as OnboardingLocation | undefined,
};

/** The exact shape written to localStorage — step + staged answers only. */
interface OnboardingDraft {
  step: number;
  department?: Department;
  sizes: Partial<SizeProfile>;
  fits: Partial<FitPreferences>;
  tasteSwipes: TasteSwipe[];
  occasions: string[];
  location?: OnboardingLocation;
}

function draftHasProgress(d: OnboardingDraft): boolean {
  return (
    d.step > 1 ||
    !!d.department ||
    Object.keys(d.sizes).length > 0 ||
    Object.keys(d.fits).length > 0 ||
    d.tasteSwipes.length > 0 ||
    d.occasions.length > 0 ||
    !!d.location
  );
}

/** Snapshot the answer fields the flow persists (never the gate cache). */
function snapshotDraft(s: OnboardingState): OnboardingDraft {
  return {
    step: s.step,
    department: s.department,
    sizes: s.sizes,
    fits: s.fits,
    tasteSwipes: s.tasteSwipes,
    occasions: s.occasions,
    location: s.location,
  };
}

function saveDraft(s: OnboardingState): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(ONBOARDING_DRAFT_KEY, JSON.stringify(snapshotDraft(s)));
  } catch {
    // Storage full / disabled (private mode) — degrade to in-memory silently.
  }
}

function loadDraft(): OnboardingDraft | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(ONBOARDING_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<OnboardingDraft>;
    // Defensive merge — a partial/legacy blob must never crash rehydration.
    return {
      step: Math.min(Math.max(Number(parsed.step) || 1, 1), ONBOARDING_STEPS),
      department: parsed.department,
      sizes: parsed.sizes ?? {},
      fits: parsed.fits ?? {},
      tasteSwipes: Array.isArray(parsed.tasteSwipes) ? parsed.tasteSwipes : [],
      occasions: Array.isArray(parsed.occasions) ? parsed.occasions : [],
      location: parsed.location,
    };
  } catch {
    return null;
  }
}

function clearDraft(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(ONBOARDING_DRAFT_KEY);
  } catch {
    /* ignore */
  }
}

export const useOnboardingStore = create<OnboardingState>((set, get) => {
  /** Apply a mutation, then mirror the resulting draft to localStorage. */
  const persist = (fn: (s: OnboardingState) => Partial<OnboardingState>) => {
    set(fn);
    saveDraft(get());
  };

  return {
    step: 1,
    completed: null,
    hydrated: false,
    resumable: false,
    ...initialAnswers,

    setStep(step) {
      persist(() => ({ step: Math.min(Math.max(step, 1), ONBOARDING_STEPS) }));
    },
    next() {
      persist((s) => ({ step: Math.min(s.step + 1, ONBOARDING_STEPS) }));
    },
    back() {
      persist((s) => ({ step: Math.max(s.step - 1, 1) }));
    },

    hydrateDraft() {
      if (get().hydrated) return; // idempotent — mount can fire twice in StrictMode
      const draft = loadDraft();
      if (draft && draftHasProgress(draft)) {
        set({ ...draft, hydrated: true, resumable: true });
      } else {
        set({ hydrated: true, resumable: false });
      }
    },
    clearResumable() {
      set({ resumable: false });
    },

    setDepartment(d) {
      persist(() => ({ department: d }));
    },
    setSize(key, value) {
      persist((s) => ({ sizes: { ...s.sizes, [key]: value } }));
    },
    setFit(key, value) {
      persist((s) => ({ fits: { ...s.fits, [key]: value } }));
    },
    addSwipe(swipe) {
      // Last swipe for a given archetype wins (a user can re-decide).
      persist((s) => ({
        tasteSwipes: [...s.tasteSwipes.filter((t) => t.archetype !== swipe.archetype), swipe],
      }));
    },
    toggleOccasion(occasion) {
      persist((s) => ({
        occasions: s.occasions.includes(occasion)
          ? s.occasions.filter((o) => o !== occasion)
          : [...s.occasions, occasion],
      }));
    },
    setLocation(location) {
      persist(() => ({ location }));
    },

    setCompleted(completed) {
      set({ completed });
    },
    reset() {
      // Drop the persisted draft too — a successful seed or "start over" wipes it.
      clearDraft();
      set({ step: 1, resumable: false, ...initialAnswers });
    },

    buildSeedPayload() {
      const s = get();

      // facts — L1 hard constraints/context read cheaply by the composer.
      const facts: Record<string, unknown> = {};
      if (s.department) facts.department = s.department;
      if (Object.keys(s.sizes).length) facts.sizes = s.sizes;
      if (Object.keys(s.fits).length) facts.fits = s.fits;
      if (s.occasions.length) facts.occasions = s.occasions;
      if (s.location) facts.location = s.location;

      // preferences — the fixed shared dimension vocabulary. Confidence is a hint;
      // the server clamps into the onboarding band.
      const preferences: OnboardingPreference[] = [];
      const liked = s.tasteSwipes.filter((t) => t.liked).map((t) => t.archetype);
      const disliked = s.tasteSwipes.filter((t) => !t.liked).map((t) => t.archetype);
      if (liked.length || disliked.length) {
        preferences.push({
          dimension: 'archetype',
          value: { liked, disliked },
          polarity: liked.length ? 'like' : 'neutral',
        });
      }
      if (s.occasions.length) {
        preferences.push({
          dimension: 'occasion',
          value: { tags: s.occasions },
          polarity: 'like',
        });
      }
      if (s.fits.top !== undefined) {
        preferences.push({ dimension: 'silhouette_top', value: { scale: s.fits.top } });
      }
      if (s.fits.bottom !== undefined) {
        preferences.push({ dimension: 'silhouette_bottom', value: { scale: s.fits.bottom } });
      }

      // signals — raw taste-deck swipes (append-only evidence for distillation).
      const signals: OnboardingSignal[] = s.tasteSwipes.map((t) => ({
        signalType: 'taste_swipe',
        key: t.archetype,
        polarity: t.liked ? 'like' : 'dislike',
        weight: 1,
      }));

      return { facts, preferences, signals };
    },
  };
});
