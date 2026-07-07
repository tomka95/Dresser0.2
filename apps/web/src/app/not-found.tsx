import { AppShell } from '@/components/layout/AppShell';
import { NotFoundState } from '@/components/ds';

/**
 * 404 in the dark app theme (§8 · E1). Renders the shared NotFoundState
 * template — hanger medallion → "This rack is empty" → "Back to Home" (/home)
 * → "404 — page not found" — inside AppShell so it keeps the closet backdrop.
 * AppShell carries no bottom nav, matching the design's chrome-less 404.
 */
export default function NotFound() {
  return (
    <AppShell scroll={false}>
      <div className="relative h-full">
        <NotFoundState />
      </div>
    </AppShell>
  );
}
