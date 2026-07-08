import { describe, expect, it } from 'vitest';
import { homeGreeting } from '@/lib/greeting';

// Fixed reference dates (local time). Weekday sanity is asserted so the test
// fails loudly if a date is miscounted rather than silently testing the wrong bucket.
const WED = new Date(2026, 6, 8, 9, 0); // 2026-07-08 Wed 09:00
const FRI = new Date(2026, 6, 10, 9, 0); // 2026-07-10 Fri
const SAT = new Date(2026, 6, 11, 15, 0); // 2026-07-11 Sat
const MON_AM = new Date(2026, 6, 13, 8, 0); // 2026-07-13 Mon 08:00

const MORNING = ['Good morning', 'Morning', 'Rise and shine'];
const AFTERNOON = ['Good afternoon', 'Afternoon', 'Hope the day’s treating you well'];
const EVENING = ['Good evening', 'Evening', 'Hope you had a good one'];
const NIGHT = ['Winding down', 'Good evening', 'Evening'];
const LATE = ['Still up', 'Burning the midnight oil', 'Up late'];

describe('homeGreeting', () => {
  it('sanity: reference weekdays are what we think', () => {
    expect(WED.getDay()).toBe(3);
    expect(FRI.getDay()).toBe(5);
    expect(SAT.getDay()).toBe(6);
    expect(MON_AM.getDay()).toBe(1);
  });

  it('appends the name when present, omits it when not', () => {
    expect(homeGreeting(FRI, 'Guy')).toBe('Happy Friday, Guy');
    expect(homeGreeting(FRI, null)).toBe('Happy Friday');
    expect(homeGreeting(FRI, '  ')).toBe('Happy Friday'); // blank name -> no comma
  });

  it('day-of-week flavor overrides time of day', () => {
    expect(homeGreeting(FRI, 'Guy')).toBe('Happy Friday, Guy');
    expect(homeGreeting(SAT, 'Guy')).toBe('Happy weekend, Guy');
    expect(homeGreeting(MON_AM, 'Guy')).toBe('Happy Monday, Guy');
  });

  it('holiday wins over everything', () => {
    const xmas = new Date(2026, 11, 25, 8, 0);
    expect(homeGreeting(xmas, 'Guy')).toBe('Merry Christmas, Guy');
    const nye = new Date(2026, 11, 31, 23, 0);
    expect(homeGreeting(nye, null)).toBe('Happy New Year’s Eve');
  });

  it('time-of-day buckets on a plain weekday', () => {
    const at = (h: number) => homeGreeting(new Date(2026, 6, 8, h, 0), 'Guy');
    expect(MORNING.some((p) => at(9) === `${p}, Guy`)).toBe(true);
    expect(AFTERNOON.some((p) => at(14) === `${p}, Guy`)).toBe(true);
    expect(EVENING.some((p) => at(18) === `${p}, Guy`)).toBe(true);
    expect(NIGHT.some((p) => at(22) === `${p}, Guy`)).toBe(true);
    expect(LATE.some((p) => at(2) === `${p}, Guy`)).toBe(true);
  });

  it('is stable within a day (no flicker between renders)', () => {
    const a = homeGreeting(new Date(2026, 6, 8, 9, 0), 'Guy');
    const b = homeGreeting(new Date(2026, 6, 8, 9, 30), 'Guy');
    expect(a).toBe(b);
  });
});
