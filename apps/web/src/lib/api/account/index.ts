/**
 * Account API client — irreversible deletion + GDPR data export.
 *
 * Both are pinned to the signed-in user by their access token; there is no target
 * id. `deleteAccount` requires the typed confirmation phrase (the server re-checks
 * it). `exportAccountData` streams the JSON export and triggers a browser download.
 */
import { getAccessToken } from '@/lib/auth';
import { API_BASE_URL } from '@/lib/api/base';

/** Permanently erase the current user's account. Caller signs out afterwards. */
export async function deleteAccount(confirmation: string): Promise<void> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/account`, {
    method: 'DELETE',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ confirmation }),
  });
  if (!response.ok) {
    throw new Error('Could not delete your account. Please try again or contact support.');
  }
}

/** Download the current user's data as a JSON file. */
export async function exportAccountData(): Promise<void> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/account/export`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error('Could not export your data. Please try again.');

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = 'tailor-data-export.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
