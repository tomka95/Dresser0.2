// STATUS: mock closet API client backed by in-memory array

import { ClosetItem } from '@tailor/contracts';

const MOCK_USER_ID = '00000000-0000-0000-0000-000000000001';

// STATUS: mock-only client; replace with real Supabase-backed API once ready.
// TODO(api): Swap this module with GET /api/closet (list) + POST /api/closet (create). See docs/contracts-notes.md.

const mockClosetItems: ClosetItem[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    userId: MOCK_USER_ID,
    name: 'White Crew Tee',
    category: 'top',
    color: 'white',
    brand: 'Everlane',
    imageUrl:
      'https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=400&q=80',
    createdAt: '2024-05-01T10:00:00.000Z',
    updatedAt: '2024-05-01T10:00:00.000Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    userId: MOCK_USER_ID,
    name: 'High-Rise Straight Jeans',
    category: 'bottom',
    color: 'mid-wash blue',
    brand: 'Levi’s',
    imageUrl:
      'https://images.unsplash.com/photo-1503341455253-b2e723bb3dbb?auto=format&fit=crop&w=400&q=80',
    createdAt: '2024-05-02T09:30:00.000Z',
    updatedAt: '2024-05-02T09:30:00.000Z',
  },
  {
    id: '33333333-3333-3333-3333-333333333333',
    userId: MOCK_USER_ID,
    name: 'Relaxed Fit Blazer',
    category: 'outerwear',
    color: 'charcoal',
    brand: 'Theory',
    imageUrl:
      'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=400&q=80',
    createdAt: '2024-05-03T08:15:00.000Z',
    updatedAt: '2024-05-03T08:15:00.000Z',
  },
  {
    id: '44444444-4444-4444-4444-444444444444',
    userId: MOCK_USER_ID,
    name: 'Minimal Leather Sneakers',
    category: 'shoes',
    color: 'white',
    brand: 'Common Projects',
    imageUrl:
      'https://images.unsplash.com/photo-1503602642458-232111445657?auto=format&fit=crop&w=400&q=80',
    createdAt: '2024-05-04T11:45:00.000Z',
    updatedAt: '2024-05-04T11:45:00.000Z',
  },
];

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

const generateId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `mock-${Math.random().toString(36).slice(2, 10)}`;
};

export async function listClosetItems(): Promise<ClosetItem[]> {
  await sleep(200);
  return mockClosetItems.map((item) => ({ ...item }));
}

export async function addClosetItem(
  input: Omit<ClosetItem, 'id' | 'userId' | 'createdAt' | 'updatedAt'>
): Promise<ClosetItem> {
  await sleep(150);
  const now = new Date().toISOString();

  const newItem: ClosetItem = {
    ...input,
    id: generateId(),
    userId: MOCK_USER_ID,
    createdAt: now,
    updatedAt: now,
  };

  mockClosetItems.push(newItem);

  return { ...newItem };
}

export { MOCK_USER_ID };


