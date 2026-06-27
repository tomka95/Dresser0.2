/**
 * Outfit suggestion API abstraction layer.
 *
 * Right now it returns mock data from the in-memory client. When the backend
 * is available we should route these calls through real HTTP endpoints such as
 * POST /api/outfits/suggest. Keeping this abstraction makes that swap a
 * one-line change for the rest of the app.
 *
 * TODO(api): Replace with real POST /api/outfits/suggest (and related GET
 * endpoints) once implemented per docs/contracts-notes.md.
 */
import type { OutfitSuggestion } from '@tailor/contracts';

import { suggestOutfits as mockSuggestOutfits } from '../outfitsClient';

type SuggestOptions = {
  limit?: number;
};

export async function suggestOutfits(
  options?: SuggestOptions
): Promise<OutfitSuggestion[]> {
  return mockSuggestOutfits(options);
}










