/**
 * Outfit feedback client (Wave S3): POSTs reject / modify / worn reactions on a
 * composed outfit to /outfits/feedback, which turns them into per-item preference
 * signals. Fire-and-forget from the caller's view — feedback must never block the
 * chat UI, so failures resolve to null.
 *
 * The server sets user_id from the JWT; this client never sends it.
 */
import type { OutfitFeedbackAck, OutfitFeedbackRequest } from '@tailor/contracts';

import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function sendOutfitFeedback(
  body: OutfitFeedbackRequest
): Promise<OutfitFeedbackAck | null> {
  let token: string | null = null;
  try {
    token = await getAccessToken();
  } catch {
    token = null;
  }
  if (!token) return null;

  try {
    const res = await fetch(`${API_BASE_URL}/outfits/feedback`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as OutfitFeedbackAck;
  } catch {
    // Best-effort — the reaction just isn't recorded this time.
    return null;
  }
}
