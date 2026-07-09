import { describe, it, expect, beforeEach } from 'vitest';
import { useOnboardingStore, ONBOARDING_STEPS } from '@/stores/useOnboardingStore';
import { STEPS } from '@/components/onboarding/steps';

function reset() {
  useOnboardingStore.getState().reset();
  useOnboardingStore.setState({ completed: null });
}

describe('useOnboardingStore', () => {
  beforeEach(reset);

  describe('STEPS registry (Fix-1 gmail_scan insertion)', () => {
    it('inserts gmail_scan immediately after sizes, keeping the rest in order', () => {
      expect(STEPS.map((s) => s.key)).toEqual([
        'departments',
        'sizes',
        'gmail_scan',
        'fits',
        'taste',
        'occasions',
        'weather',
      ]);
    });

    it('gmail_scan is optional (skippable + always complete) so connect never blocks', () => {
      const gmail = STEPS[2];
      expect(gmail.key).toBe('gmail_scan');
      expect(gmail.skippable).toBe(true);
      expect(gmail.isComplete(useOnboardingStore.getState())).toBe(true);
    });

    it('ONBOARDING_STEPS stays in lockstep with the registry length (now 7)', () => {
      expect(ONBOARDING_STEPS).toBe(7);
      expect(ONBOARDING_STEPS).toBe(STEPS.length);
    });
  });

  describe('navigation', () => {
    it('clamps next/back within [1, ONBOARDING_STEPS]', () => {
      const { next, back } = useOnboardingStore.getState();
      back(); // already at 1
      expect(useOnboardingStore.getState().step).toBe(1);
      for (let i = 0; i < ONBOARDING_STEPS + 3; i++) next();
      expect(useOnboardingStore.getState().step).toBe(ONBOARDING_STEPS);
    });

    it('setStep clamps out-of-range values', () => {
      useOnboardingStore.getState().setStep(99);
      expect(useOnboardingStore.getState().step).toBe(ONBOARDING_STEPS);
      useOnboardingStore.getState().setStep(-5);
      expect(useOnboardingStore.getState().step).toBe(1);
    });
  });

  describe('setters', () => {
    it('last swipe for an archetype wins', () => {
      const { addSwipe } = useOnboardingStore.getState();
      addSwipe({ archetype: 'minimal', liked: false });
      addSwipe({ archetype: 'minimal', liked: true });
      const swipes = useOnboardingStore.getState().tasteSwipes;
      expect(swipes).toHaveLength(1);
      expect(swipes[0].liked).toBe(true);
    });

    it('toggleOccasion adds then removes', () => {
      const { toggleOccasion } = useOnboardingStore.getState();
      toggleOccasion('work');
      expect(useOnboardingStore.getState().occasions).toEqual(['work']);
      toggleOccasion('work');
      expect(useOnboardingStore.getState().occasions).toEqual([]);
    });
  });

  describe('buildSeedPayload', () => {
    it('maps staged answers into facts/preferences/signals with fixed dimensions', () => {
      const s = useOnboardingStore.getState();
      s.setDepartment('womens');
      s.setSize('top', 'M');
      s.setFit('top', 4);
      s.addSwipe({ archetype: 'minimal', liked: true });
      s.addSwipe({ archetype: 'edgy', liked: false });
      s.toggleOccasion('work');

      const payload = useOnboardingStore.getState().buildSeedPayload();

      expect(payload.facts).toMatchObject({
        department: 'womens',
        sizes: { top: 'M' },
        fits: { top: 4 },
        occasions: ['work'],
      });

      const dims = (payload.preferences ?? []).map((p) => p.dimension);
      expect(dims).toContain('archetype');
      expect(dims).toContain('occasion');
      expect(dims).toContain('silhouette_top');

      const archetypePref = payload.preferences?.find((p) => p.dimension === 'archetype');
      expect(archetypePref?.value).toMatchObject({ liked: ['minimal'], disliked: ['edgy'] });

      // one signal per swipe, forced signalType
      expect(payload.signals).toHaveLength(2);
      expect(payload.signals?.every((sig) => sig.signalType === 'taste_swipe')).toBe(true);
    });

    it('omits empty sections (nothing staged -> empty payload parts)', () => {
      const payload = useOnboardingStore.getState().buildSeedPayload();
      expect(payload.facts).toEqual({});
      expect(payload.preferences).toEqual([]);
      expect(payload.signals).toEqual([]);
    });
  });
});
