import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// jsdom does not implement object URLs. Components that preview a selected file
// (e.g. OutfitImageUpload) call URL.createObjectURL / revokeObjectURL, which would
// otherwise throw under jsdom. Stub them globally — this is an environment gap,
// not a component bug.
URL.createObjectURL = vi.fn(() => 'blob:mock-object-url');
URL.revokeObjectURL = vi.fn();

// Cleanup after each test
afterEach(() => {
  cleanup();
});






