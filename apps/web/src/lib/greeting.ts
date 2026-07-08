/**
 * Smart, time- and date-aware Home greeting (in the spirit of Claude desktop).
 *
 * Priority: a holiday wins, then late-night, then day-of-week flavor (Friday /
 * weekend / Monday), otherwise a time-of-day phrase. Each bucket has a few
 * variants; the pick is seeded by day-of-year so the greeting is STABLE within a
 * given day (no flicker between re-renders / no SSR-vs-client mismatch) yet
 * refreshes from one day to the next.
 *
 * Pure + deterministic (all inputs are the passed `Date`) — unit tested.
 */

const MORNING = ['Good morning', 'Morning', 'Rise and shine'];
const AFTERNOON = ['Good afternoon', 'Afternoon', 'Hope the day’s treating you well'];
const EVENING = ['Good evening', 'Evening', 'Hope you had a good one'];
const NIGHT = ['Winding down', 'Good evening', 'Evening']; // 21:00–24:00
const LATE = ['Still up', 'Burning the midnight oil', 'Up late']; // 00:00–05:00

// (month 1–12)-(day) → a fixed greeting. Kept small and broadly-friendly.
const HOLIDAYS: Record<string, string> = {
  '1-1': 'Happy New Year',
  '2-14': 'Happy Valentine’s Day',
  '7-4': 'Happy Fourth',
  '10-31': 'Happy Halloween',
  '11-1': 'Happy November',
  '12-24': 'Happy Christmas Eve',
  '12-25': 'Merry Christmas',
  '12-31': 'Happy New Year’s Eve',
};

function dayOfYear(d: Date): number {
  const start = new Date(d.getFullYear(), 0, 0);
  return Math.floor((d.getTime() - start.getTime()) / 86_400_000);
}

/** Attach the name if we have one ("Good morning, Guy" / "Good morning"). */
function withName(phrase: string, name: string | null): string {
  const clean = name?.trim();
  return clean ? `${phrase}, ${clean}` : phrase;
}

/**
 * The Home greeting for `now` and an optional first name.
 *
 * @param now  the current local time (caller passes `new Date()`)
 * @param name the user's first name, or null for a name-less greeting
 */
export function homeGreeting(now: Date, name: string | null | undefined): string {
  const who = name ?? null;
  const hour = now.getHours();
  const day = now.getDay(); // 0 Sun … 6 Sat
  const seed = dayOfYear(now);
  const pick = (pool: string[]) => pool[seed % pool.length];

  // 1) Holiday — always wins.
  const holiday = HOLIDAYS[`${now.getMonth() + 1}-${now.getDate()}`];
  if (holiday) return withName(holiday, who);

  // 2) Late night wins over day-of-week flavor.
  if (hour < 5) return withName(pick(LATE), who);

  // 3) Day-of-week flavor (daytime/evening).
  if (day === 5) return withName('Happy Friday', who);
  if (day === 0 || day === 6) return withName('Happy weekend', who);
  if (day === 1 && hour < 12) return withName('Happy Monday', who);

  // 4) Time-of-day.
  if (hour < 12) return withName(pick(MORNING), who);
  if (hour < 17) return withName(pick(AFTERNOON), who);
  if (hour < 21) return withName(pick(EVENING), who);
  return withName(pick(NIGHT), who);
}
