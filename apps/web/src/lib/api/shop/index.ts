/**
 * Shop / Stage-1 feed API client (§6 · F1/F2).
 *
 * Talks to the FastAPI backend:
 *   - GET  /shop            — the closet-aware ranked feed (heterogeneous cards)
 *   - POST /clicks          — mints a click id for a product (monetized)
 *   - GET  /out/{clickId}   — 302 → destination (PUBLIC, top-level browser nav)
 *
 * MONETIZATION BOUNDARY (security-critical): the ranker/feed carries ONLY a
 * productId. The client mints a click then follows /out/{clickId} as a real
 * top-level navigation. The destination / affiliate URL is NEVER sent to or
 * constructed by the client — it is resolved server-side inside the /out
 * redirect. Do not add any code here that builds or exposes a destination URL.
 */
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/* ── Typed errors ─────────────────────────────────────────────────────────── */

/** Thrown when the session is missing/expired (401/403). */
export class ShopAuthError extends Error {
  constructor(message = 'Not authenticated. Please sign in first.') {
    super(message);
    this.name = 'ShopAuthError';
  }
}

/** Thrown for 5xx / transport failures — the feed couldn't load. */
export class ShopServerError extends Error {
  constructor(message = 'Something went wrong. Please try again.') {
    super(message);
    this.name = 'ShopServerError';
  }
}

/* ── Card shapes ──────────────────────────────────────────────────────────── */

/** The exploration flag a card echoes so the client can label + log it honestly. */
export interface CardExploration {
  isExploration?: boolean;
  reason?: string;
}

/** A shoppable product referenced by a feed card. Carries ONLY an id + display. */
export interface ShopProductRef {
  productId: string;
  name: string;
  brand: string;
  imageUrl: string;
  price: number;
}

/** Context describing which wardrobe gap a product fills. */
export interface GapContext {
  fillsEmptyOccasion?: boolean;
  category?: string | null;
}

/** A "goes with" thumbnail — an owned closet piece the product pairs with. */
export interface GoesWithItem {
  itemId?: string;
  imageUrl?: string | null;
  name?: string | null;
}

/** Fields common to every card (feed-position + telemetry echo). */
interface CardBase {
  feedPosition: number;
  cardType: 'product' | 'outfit';
  exploration?: CardExploration | null;
  score?: number;
}

/** Product card — a single buyable item ranked by outfit-unlock math. */
export interface ProductCard extends CardBase {
  type: 'product';
  cardType: 'product';
  product: ShopProductRef;
  unlockCount: number;
  /** e.g. "Unlocks 3 new outfits with your closet". */
  headline: string;
  gapContext?: GapContext | null;
  /** Owned closet pieces this product pairs with ("goes with" strip). */
  goesWith?: GoesWithItem[];
}

/** An outfit slot — an owned piece, or the single buyable piece in the look. */
export interface OutfitSlot {
  itemId?: string;
  imageUrl?: string | null;
  name?: string | null;
  brand?: string | null;
  /** Present when this slot is the buyable product in the outfit. */
  product?: ShopProductRef | null;
  owned?: boolean;
}

/** Outfit card — a collage of owned pieces + exactly one buyable piece. */
export interface OutfitCard extends CardBase {
  type: 'outfit';
  cardType: 'outfit';
  collageUrl?: string | null;
  rationale: string;
  slots?: OutfitSlot[];
  /** The single buyable product in the look. */
  buyable?: ShopProductRef | null;
}

export type Card = ProductCard | OutfitCard;

export type ShopFraming = 'personalized' | 'starter_looks';

export interface ShopFeedResponse {
  cards: Card[];
  cursor: number;
  sessionId: string;
  hasMore: boolean;
  framing: ShopFraming;
  diagnostics?: Record<string, unknown>;
}

export interface GetShopFeedParams {
  cursor?: number;
  /** Stable across pages — echo the sessionId returned by page 1. */
  sessionId?: string;
  pageSize?: number;
}

/* ── Endpoints ────────────────────────────────────────────────────────────── */

function throwForStatus(status: number): never {
  if (status === 401 || status === 403) throw new ShopAuthError();
  throw new ShopServerError();
}

/**
 * GET /shop — the ranked, closet-aware Stage-1 feed. `sessionId` is a watermark:
 * pass page 1's returned sessionId on subsequent pages to keep pagination stable.
 */
export async function getShopFeed(
  params: GetShopFeedParams = {},
): Promise<ShopFeedResponse> {
  const token = await getAccessToken();
  if (!token) throw new ShopAuthError();

  const url = new URL(`${API_BASE_URL}/shop`);
  if (params.cursor != null) url.searchParams.set('cursor', String(params.cursor));
  if (params.sessionId) url.searchParams.set('sessionId', params.sessionId);
  if (params.pageSize != null) url.searchParams.set('pageSize', String(params.pageSize));

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    // Network / transport failure.
    throw new ShopServerError('Network error. Check your connection and try again.');
  }

  if (!response.ok) throwForStatus(response.status);

  return response.json() as Promise<ShopFeedResponse>;
}

/**
 * POST /clicks — mints a click id for a product on a given surface. Returns the
 * opaque clickId; the destination is resolved server-side by /out/{clickId}.
 */
export async function mintClick(productId: string, surface: string): Promise<string> {
  const token = await getAccessToken();
  if (!token) throw new ShopAuthError();

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/clicks`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ productId, surface }),
    });
  } catch {
    throw new ShopServerError('Network error. Check your connection and try again.');
  }

  if (!response.ok) throwForStatus(response.status);

  const data = (await response.json()) as { clickId: string };
  return data.clickId;
}

/**
 * Open a product: mint a click, then follow the monetized redirect as a REAL
 * top-level browser navigation. The client never sees or builds the destination
 * URL — only the opaque clickId. This is the single, sanctioned monetization hop.
 */
export async function openProduct(productId: string, surface: string): Promise<void> {
  const clickId = await mintClick(productId, surface);
  // Top-level navigation (NOT fetch) — /out/{clickId} 302s to the destination.
  window.location.href = `${API_BASE_URL}/out/${clickId}`;
}
