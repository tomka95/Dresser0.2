// API client for Gmail endpoints
import { getAccessToken } from '@/lib/auth';

// ─── Ingest types ─────────────────────────────────────────────────────────────

export interface IngestProgress {
  fetched: number;
  filtered: number;
  extracted: number;
  total_estimate: number | null;
}

export interface IngestStatus {
  // Backend emits 'running' | 'completed' | 'error'. ('failed' kept for back-compat.)
  sync_id: string;
  status: 'running' | 'completed' | 'error' | 'failed';
  progress: IngestProgress;
  started_at: string | null;
  finished_at: string | null;
}

export interface CandidateSource {
  merchant: string | null;
  order_id: string | null;
  message_id: string | null;
  google_account_id: number | null;
  email_date: string | null;
}

export interface IngestCandidate {
  candidate_id: string;
  name: string | null;
  brand: string | null;
  category: string | null;
  color: string | null;
  size: string | null;
  qty: number;
  unit_price: number | null;
  currency: string | null;
  order_date: string | null;
  is_return: boolean;
  image_url: string | null;
  // Image lifecycle for the streaming deck (Phase 4):
  //   'resolved'    — image_url is present (verified).
  //   'pending'     — still resolving in the background → shimmer + keep polling.
  //   'placeholder' — slow tiers exhausted, no image found → static placeholder.
  image_status: 'resolved' | 'pending' | 'placeholder' | 'user_uploaded' | null;
  confidence_overall: number | null;
  low_confidence_fields: string[];
  seen_count: number;
  // Ingestion source — drives the source-aware deck badge. The candidates/confirm/
  // status endpoints are source-agnostic; only this tag differs between Gmail and
  // photo-uploaded items.
  source_type: 'gmail' | 'photo';
  source: CandidateSource;
}

export interface ConfirmRequest {
  accepted: string[];
  rejected: string[];
  edits: Record<string, Record<string, unknown>>;
}

export interface ConfirmWrittenItem {
  clothing_item_id: string;
  candidate_id: string;
  name: string;
  inserted: boolean;
}

export interface ConfirmResponse {
  accepted_count: number;
  rejected_count: number;
  inserted_count: number;
  updated_count: number;
  written: ConfirmWrittenItem[];
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface GmailConnectionStatus {
  connected: boolean;
  scope: string | null;
  connected_at: string | null;
}

/**
 * Begin the Gmail-connect OAuth flow.
 *
 * The backend builds the Google consent URL (dedicated gmail.readonly client)
 * and a signed, user-bound `state`. We never construct the consent URL or hold
 * any client secret on the frontend; we just navigate to the URL the backend
 * returns. Google then redirects back to the /gmail/oauth/callback Route Handler.
 */
export async function startGmailConnect(): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/oauth/start`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error('Could not start Gmail connection. Please try again.');
  }

  const { url } = (await response.json()) as { url: string };
  if (!url) {
    throw new Error('Server did not return a Gmail authorization URL.');
  }
  // Full-page navigation to Google's consent screen.
  window.location.href = url;
}

/** Read whether the current user has a usable (refresh-token-bearing) Gmail connection. */
export async function fetchGmailConnectionStatus(): Promise<GmailConnectionStatus> {
  const token = await getAccessToken();
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/oauth/status`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error('Failed to read Gmail connection status.');
  }

  return response.json();
}

export interface GmailClothingItem {
  name: string;
  store: string | null;
  price: number | null;
  image: string | null;
}

export interface ExtractClothingResponse {
  connected: boolean;
  items: GmailClothingItem[];
}

/**
 * Extract clothing items from Gmail purchase emails.
 * Requires authenticated user with Gmail access.
 * 
 * @returns Promise with connected status and array of clothing items
 * @throws Error if extraction fails or user is not authenticated
 */
export async function extractClothingFromGmail(): Promise<ExtractClothingResponse> {
  // Get the Supabase access token from the current session
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/clothing-items`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    
    // Handle FastAPI validation errors (422)
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    
    // Handle specific error cases
    if (response.status === 401 || response.status === 403) {
      throw new Error('Gmail access not granted. Please reconnect your Google account.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string'
        ? error.detail
        : 'Failed to extract clothing items from Gmail'
    );
  }

  return response.json();
}

// ─── Phase 3d-b ingest API ────────────────────────────────────────────────────

/** Start a 2-year Gmail receipt sync. Returns {sync_id} for polling.
 *  If a sync is already running (409), returns its sync_id so the caller can poll it. */
export async function startIngest(): Promise<{ sync_id: string }> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/gmail/ingest/start`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (response.status === 409) {
    const error = await response.json().catch(() => ({}));
    const match =
      typeof error.detail === 'string' && error.detail.match(/sync_id=([0-9a-f-]+)/i);
    if (match) return { sync_id: match[1] };
    throw new Error('A sync is already running.');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to start sync.');
  }

  return response.json();
}

/** Poll a sync run's status and progress. */
export async function getIngestStatus(syncId: string): Promise<IngestStatus> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(
    `${API_BASE_URL}/gmail/ingest/status?sync_id=${encodeURIComponent(syncId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );

  if (!response.ok) throw new Error('Failed to get sync status.');
  return response.json();
}

/** Fetch the authenticated user's status='pending' candidates for the swipe deck. */
export async function getIngestCandidates(): Promise<IngestCandidate[]> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/gmail/ingest/candidates`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error('Failed to load candidates.');
  return response.json();
}

// ─── Photo ingest (Wave 1) ──────────────────────────────────────────────────
// A SECOND ingestion source that feeds the SAME candidates/confirm/status spine as
// Gmail. Only the start call differs (a multipart photo upload instead of a Gmail
// sync); everything downstream is shared.

export interface PhotoIngestResponse {
  sync_id: string;
  images_processed: number;
  staged: number;
  duplicates: number;
  held_multi_person: number;
  message: string | null;
}

/** Upload one or more photos; each garment is detected, cut out, and staged as a
 *  pending candidate for the shared review deck. Processing is inline (no polling). */
export async function startPhotoIngest(files: File[]): Promise<PhotoIngestResponse> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const formData = new FormData();
  for (const f of files) formData.append('files', f);

  const response = await fetch(`${API_BASE_URL}/photo/ingest/start`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (Array.isArray(error.detail)) {
      throw new Error(error.detail.map((e: any) => e.msg).join(', '));
    }
    throw new Error(
      typeof error.detail === 'string' ? error.detail : 'Failed to process photos.',
    );
  }

  return response.json();
}

/** Confirm (accept/reject/edit) a batch of candidates.
 *  Accepted ones are upserted into clothing_items. Rejected ones write nothing. */
export async function confirmCandidates(body: ConfirmRequest): Promise<ConfirmResponse> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/gmail/ingest/confirm`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === 'string' ? error.detail : 'Failed to confirm candidates.',
    );
  }

  return response.json();
}
