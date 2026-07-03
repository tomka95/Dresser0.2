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
 * IN-MEMORY ONLY (zustand, no persist). Screens write here as the user taps; the
 * whole thing commits ONCE via POST /onboarding/seed at step-6 completion
 * (buildSeedPayload). Nothing sensitive is persisted to localStorage — abandoning
 * onboarding drops the staged answers and, because onboarding_completed_at is only
 * stamped on a successful seed, the gate re-enters the user at step 1.
 *
 * `completed` caches a known-onboarded result so the gate can short-circuit the
 * status fetch on later navigations (set true after a successful seed OR after the
 * gate observes status.completed).
 */

export const ONBOARDING_STEPS = 6;

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

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  step: 1,
  completed: null,
  ...initialAnswers,

  setStep(step) {
    set({ step: Math.min(Math.max(step, 1), ONBOARDING_STEPS) });
  },
  next() {
    set((s) => ({ step: Math.min(s.step + 1, ONBOARDING_STEPS) }));
  },
  back() {
    set((s) => ({ step: Math.max(s.step - 1, 1) }));
  },

  setDepartment(d) {
    set({ department: d });
  },
  setSize(key, value) {
    set((s) => ({ sizes: { ...s.sizes, [key]: value } }));
  },
  setFit(key, value) {
    set((s) => ({ fits: { ...s.fits, [key]: value } }));
  },
  addSwipe(swipe) {
    // Last swipe for a given archetype wins (a user can re-decide).
    set((s) => ({
      tasteSwipes: [...s.tasteSwipes.filter((t) => t.archetype !== swipe.archetype), swipe],
    }));
  },
  toggleOccasion(occasion) {
    set((s) => ({
      occasions: s.occasions.includes(occasion)
        ? s.occasions.filter((o) => o !== occasion)
        : [...s.occasions, occasion],
    }));
  },
  setLocation(location) {
    set({ location });
  },

  setCompleted(completed) {
    set({ completed });
  },
  reset() {
    set({ step: 1, ...initialAnswers });
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
}));
