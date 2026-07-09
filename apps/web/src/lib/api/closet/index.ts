/**
 * Closet API abstraction layer.
 *
 * Connects to FastAPI backend endpoints at /closet.
 */
import type { ClosetItem, ClosetItemUpdate } from '@tailor/contracts';
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function listClosetItems(options?: { includeTags?: boolean }): Promise<ClosetItem[]> {
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  // Construct URL (includeTags ignored for backward compatibility)
  const url = new URL(`${API_BASE_URL}/closet`);

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: {
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
      throw new Error('Not authenticated. Please sign in first.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string' 
        ? error.detail 
        : 'Failed to load closet items'
    );
  }

  return response.json();
}

export async function getClosetItem(id: string): Promise<ClosetItem> {
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/closet/${id}`, {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    
    // Handle 404 Not Found
    if (response.status === 404) {
      throw new Error(`Closet item not found: ${id}`);
    }
    
    // Handle FastAPI validation errors (422)
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    
    // Handle specific error cases
    if (response.status === 401 || response.status === 403) {
      throw new Error('Not authenticated. Please sign in first.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string' 
        ? error.detail 
        : 'Failed to get closet item'
    );
  }

  return response.json();
}

export async function patchClosetItem(
  id: string,
  updates: ClosetItemUpdate
): Promise<ClosetItem> {
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/closet/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(updates),
  });

  if (!response.ok) {
    const error = await response.json();
    
    // Handle 404 Not Found
    if (response.status === 404) {
      throw new Error(`Closet item not found: ${id}`);
    }
    
    // Handle FastAPI validation errors (422)
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    
    // Handle specific error cases
    if (response.status === 401 || response.status === 403) {
      throw new Error('Not authenticated. Please sign in first.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string' 
        ? error.detail 
        : 'Failed to update closet item'
    );
  }

  return response.json();
}

export interface RegenerateImageResult {
  status: string; // 'regenerating'
  generationStatus: string; // 'generating'
}

/**
 * Kick off a background regeneration of an item's product-card image.
 *
 * multipart/form-data: an OPTIONAL `reason` ("what was wrong?" correction, steers +
 * verify-gated server-side) and an OPTIONAL `reference` image the server conditions the
 * generation on (validated + sanitized server-side). ANY item is eligible now (Gmail /
 * image-less too). Returns immediately (202) with generationStatus 'generating'; the caller
 * polls getClosetItem until generationStatus leaves 'generating', then compares imageUrl
 * (changed → new verified card; unchanged → verify miss, current image kept).
 *
 * NOTE: do NOT set Content-Type — the browser adds the multipart boundary itself (mirrors
 * the photo-ingest upload in lib/api/gmail). Setting application/json here would break it.
 */
export async function regenerateItemImage(
  id: string,
  reason?: string,
  reference?: File | null
): Promise<RegenerateImageResult> {
  const token = await getAccessToken();

  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const formData = new FormData();
  if (reason && reason.trim()) formData.append('reason', reason.trim());
  if (reference) formData.append('reference', reference);

  const response = await fetch(`${API_BASE_URL}/closet/${id}/regenerate`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    if (response.status === 404) {
      throw new Error(`Closet item not found: ${id}`);
    }
    if (response.status === 400) {
      throw new Error(
        typeof error.detail === 'string'
          ? error.detail
          : "This item's image can't be regenerated."
      );
    }
    if (response.status === 401 || response.status === 403) {
      throw new Error('Not authenticated. Please sign in first.');
    }
    if (Array.isArray(error.detail)) {
      throw new Error(error.detail.map((err: any) => err.msg).join(', '));
    }
    throw new Error(
      typeof error.detail === 'string' ? error.detail : 'Failed to start regeneration'
    );
  }

  return response.json();
}

/** 202 response for a manual add (Photo-seam Phase 4): the item is staged as a
 *  candidate, tailored through the shared generation seam, and born through the
 *  confirm chokepoint when ready — it appears in the closet shortly after.
 *  Poll GET /gmail/ingest/status?sync_id= (settled) if progress UI is needed. */
export interface ManualAddResponse {
  status: 'tailoring';
  syncId: string;
  candidateId: string;
  message: string;
}

export async function addClosetItem(
  input: Omit<ClosetItem, 'id' | 'userId' | 'createdAt' | 'updatedAt' | 'analysisRaw'>
): Promise<ManualAddResponse> {
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/closet`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(input),
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
      throw new Error('Not authenticated. Please sign in first.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string' 
        ? error.detail 
        : 'Failed to add closet item'
    );
  }

  return response.json();
}








