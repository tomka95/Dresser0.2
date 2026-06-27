// STATUS: mock outfit suggestion client returning hard-coded data

import { OutfitSuggestion } from '@tailor/contracts';

import { listClosetItems, MOCK_USER_ID } from './closetClient';

// TODO(api): Replace with POST /api/outfits/suggest + GET /api/outfits once backend endpoints exist (see docs/contracts-notes.md).

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

const generateId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `mock-outfit-${Math.random().toString(36).slice(2, 10)}`;
};

type SuggestOptions = {
  limit?: number;
};

export async function suggestOutfits(
  options: SuggestOptions = {}
): Promise<OutfitSuggestion[]> {
  const { limit = 2 } = options;

  await sleep(250);

  const closetItems = await listClosetItems();
  if (closetItems.length === 0) {
    return [];
  }

  const closetMap = new Map(closetItems.map((item) => [item.id, item]));

  const outfits: OutfitSuggestion[] = [
    {
      id: 'aaaa1111-aaaa-1111-aaaa-111111111111',
      userId: closetItems[0]?.userId ?? MOCK_USER_ID,
      name: 'Weekend Coffee Run',
      occasion: 'Casual Saturday',
      items: [
        '11111111-1111-1111-1111-111111111111', // White tee
        '22222222-2222-2222-2222-222222222222', // Jeans
        '44444444-4444-4444-4444-444444444444', // Sneakers
      ].filter((id) => closetMap.has(id)),
      createdAt: new Date().toISOString(),
    },
    {
      id: 'bbbb2222-bbbb-2222-bbbb-222222222222',
      userId: closetItems[0]?.userId ?? MOCK_USER_ID,
      name: 'Client Pitch',
      occasion: 'Smart Casual Work',
      items: [
        '33333333-3333-3333-3333-333333333333', // Blazer
        '22222222-2222-2222-2222-222222222222', // Jeans
      ].filter((id) => closetMap.has(id)),
      recommendedItems: [
        {
          id: '55555555-5555-5555-5555-555555555555',
          name: 'Camel Wool Coat',
          reason: 'Adds polish and warmth for colder client meetings',
        },
      ],
      createdAt: new Date().toISOString(),
    },
  ];

  return outfits.slice(0, limit).map((outfit) => ({
    ...outfit,
    items: [...outfit.items],
    recommendedItems: outfit.recommendedItems
      ? [...outfit.recommendedItems]
      : undefined,
  }));
}










