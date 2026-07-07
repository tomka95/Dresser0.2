import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// jsdom does not implement object URLs. Components that preview a selected file
// (e.g. OutfitImageUpload) call URL.createObjectURL / revokeObjectURL, which would
// otherwise throw under jsdom. Stub them globally — this is an environment gap,
// not a component bug.
URL.createObjectURL = vi.fn(() => 'blob:mock-object-url');
URL.revokeObjectURL = vi.fn();

// jsdom does not implement matchMedia. The ds/ loaders (LottieMark) query
// prefers-reduced-motion in an effect; without this any test rendering a
// ds-barrel component throws. Environment gap, not a component bug.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// jsdom does not implement IntersectionObserver. The ds/ loaders (LottieMark,
// via DeckLoading/Thinking) construct one in an effect to play only while on
// screen; without this any test rendering a ds loader (e.g. the /review deck's
// loading state) throws an uncaught ReferenceError that tears down the render.
// Environment gap, not a component bug — same class as the matchMedia stub above.
if (typeof globalThis.IntersectionObserver === 'undefined') {
  class MockIntersectionObserver {
    constructor(_cb: IntersectionObserverCallback, _opts?: IntersectionObserverInit) {}
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
    readonly root = null;
    readonly rootMargin = '';
    readonly thresholds = [];
  }
  globalThis.IntersectionObserver =
    MockIntersectionObserver as unknown as typeof IntersectionObserver;
  if (typeof window !== 'undefined') {
    window.IntersectionObserver =
      MockIntersectionObserver as unknown as typeof IntersectionObserver;
  }
}

// Cleanup after each test
afterEach(() => {
  cleanup();
});






