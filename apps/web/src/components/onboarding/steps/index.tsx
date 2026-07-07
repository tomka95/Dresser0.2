'use client';

import React, { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { MapPin, Camera, Check, ChevronRight } from 'lucide-react';
import {
  DEPARTMENTS,
  DEPARTMENT_LABELS,
  LETTER_SIZES,
  DRESS_SIZES,
  SHOE_SYSTEMS,
  sizeKeysForDepartment,
  FIT_SLIDERS,
  type Department,
  type BottomSize,
  type ShoeSize,
} from '@tailor/contracts';

import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { seedOnboarding } from '@/lib/api/onboarding';
import { startGmailConnect } from '@/lib/api/gmail';
import { GmailGlyph, M, Spark, Medallion } from '@/components/ds';
import { OnboardingStep } from '../OnboardingStep';
import { OptionCard, Chip, Segmented, FieldBlock } from './_controls';
import { FitSlider } from './_FitSlider';
import { TasteDeck } from './_TasteDeck';

/**
 * Step registry for the onboarding flow — the six real screen bodies, restyled to
 * the redesign material system (§2). Every screen is tap/slider/chip only (zero
 * free text), one question per screen, and writes staged answers to
 * useOnboardingStore. Nothing hits the server until the shell's single
 * seedOnboarding() at Finish (screen 6 can commit early when the user hands off to
 * a closet-seed flow — see WeatherScreen).
 *
 * `isComplete(state)` gates the Continue button; `skippable` lets a user advance
 * without answering. Only screens 1 (departments) and 2 (sizes) are required, so
 * their predicates are the ones that actually gate.
 */
export interface StepDef {
  key: string;
  title: string;
  skippable: boolean;
  Component: React.FC;
  /** True when the step has enough staged data to advance. */
  isComplete: (s: ReturnType<typeof useOnboardingStore.getState>) => boolean;
}

// ── Screen 1: departments ────────────────────────────────────────────────────
const DEPT_HINTS: Record<Department, string> = {
  womens: "Women's departments and sizing",
  mens: "Men's departments and sizing",
  both: 'Shop across both',
  gender_neutral: 'Skip the gendered split',
};

const DepartmentsScreen: React.FC = () => {
  const department = useOnboardingStore((s) => s.department);
  const setDepartment = useOnboardingStore((s) => s.setDepartment);
  return (
    <OnboardingStep
      title="What do you wear?"
      subtitle="Sets which departments Tailor shops and styles from."
    >
      <div role="radiogroup" aria-label="Department" className="flex flex-col gap-[11px]">
        {DEPARTMENTS.map((d) => (
          <OptionCard
            key={d}
            active={department === d}
            onClick={() => setDepartment(d)}
            label={DEPARTMENT_LABELS[d]}
            hint={DEPT_HINTS[d]}
          />
        ))}
      </div>
    </OnboardingStep>
  );
};

// ── Screen 2: sizes ──────────────────────────────────────────────────────────
const WAIST_VALUES = [26, 28, 30, 32, 34, 36, 38, 40];
const INSEAM_VALUES = [28, 30, 32, 34];
const SHOE_VALUES: Record<(typeof SHOE_SYSTEMS)[number], string[]> = {
  US: ['6', '7', '8', '9', '10', '11', '12', '13'],
  EU: ['38', '39', '40', '41', '42', '43', '44', '45', '46'],
  UK: ['5', '6', '7', '8', '9', '10', '11', '12'],
};

const SizesScreen: React.FC = () => {
  const department = useOnboardingStore((s) => s.department) ?? 'womens';
  const sizes = useOnboardingStore((s) => s.sizes);
  const setSize = useOnboardingStore((s) => s.setSize);

  const keys = sizeKeysForDepartment(department).filter((k) => k !== 'outerwear');
  const showDress = keys.includes('dress');

  // Local system switches — the store holds the resolved value; the segment lets a
  // user flip systems before they've picked a value in the new one.
  const { bottom, shoe } = sizes;
  const [bottomSystem, setBottomSystem] = useState<'letter' | 'waist_inseam'>(
    bottom?.system ?? (department === 'mens' ? 'waist_inseam' : 'letter'),
  );
  const [shoeSystem, setShoeSystem] = useState<(typeof SHOE_SYSTEMS)[number]>(shoe?.system ?? 'US');

  const setBottomWaist = (waist: number) => {
    const inseam = bottom?.system === 'waist_inseam' ? bottom.inseam : undefined;
    setSize('bottom', { system: 'waist_inseam', waist, inseam } as BottomSize);
  };
  const setBottomInseam = (inseam: number) => {
    if (bottom?.system !== 'waist_inseam') return; // inseam needs a waist first
    setSize('bottom', { system: 'waist_inseam', waist: bottom.waist, inseam } as BottomSize);
  };

  return (
    <OnboardingStep
      title="Your sizes"
      subtitle="So everything we suggest actually fits. Change anytime in Settings."
    >
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pb-2">
        {/* Top */}
        <FieldBlock label="Top" required>
          <div className="flex flex-wrap gap-2">
            {LETTER_SIZES.map((sz) => (
              <Chip key={sz} active={sizes.top === sz} onClick={() => setSize('top', sz)}>
                {sz}
              </Chip>
            ))}
          </div>
        </FieldBlock>

        {/* Bottom — letter OR waist(×inseam) */}
        <FieldBlock label="Bottom" required>
          <div className="mb-3 max-w-[220px]">
            <Segmented
              ariaLabel="Bottom size system"
              options={['letter', 'waist_inseam'] as const}
              value={bottomSystem}
              onChange={setBottomSystem}
              labelFor={(o) => (o === 'letter' ? 'Letter' : 'Waist')}
            />
          </div>
          {bottomSystem === 'letter' ? (
            <div className="flex flex-wrap gap-2">
              {LETTER_SIZES.map((sz) => (
                <Chip
                  key={sz}
                  active={bottom?.system === 'letter' && bottom.value === sz}
                  onClick={() => setSize('bottom', { system: 'letter', value: sz } as BottomSize)}
                >
                  {sz}
                </Chip>
              ))}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {WAIST_VALUES.map((w) => (
                  <Chip
                    key={w}
                    active={bottom?.system === 'waist_inseam' && bottom.waist === w}
                    onClick={() => setBottomWaist(w)}
                  >
                    {w}
                  </Chip>
                ))}
              </div>
              <div className="mb-2 mt-3">
                <FieldBlock label="Inseam">
                  <div className="flex flex-wrap gap-2">
                    {INSEAM_VALUES.map((n) => (
                      <Chip
                        key={n}
                        active={bottom?.system === 'waist_inseam' && bottom.inseam === n}
                        onClick={() => setBottomInseam(n)}
                      >
                        {n}
                      </Chip>
                    ))}
                  </div>
                </FieldBlock>
              </div>
            </>
          )}
        </FieldBlock>

        {/* Shoe */}
        <FieldBlock label="Shoe">
          <div className="mb-3 max-w-[220px]">
            <Segmented
              ariaLabel="Shoe size system"
              options={SHOE_SYSTEMS}
              value={shoeSystem}
              onChange={setShoeSystem}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {SHOE_VALUES[shoeSystem].map((v) => (
              <Chip
                key={v}
                active={shoe?.system === shoeSystem && shoe.value === v}
                onClick={() => setSize('shoe', { system: shoeSystem, value: v } as ShoeSize)}
              >
                {v}
              </Chip>
            ))}
          </div>
        </FieldBlock>

        {/* Dress — womens / both only */}
        {showDress ? (
          <FieldBlock label="Dress">
            <div className="flex flex-wrap gap-2">
              {DRESS_SIZES.map((sz) => (
                <Chip key={sz} active={sizes.dress === sz} onClick={() => setSize('dress', sz)}>
                  {sz}
                </Chip>
              ))}
            </div>
          </FieldBlock>
        ) : null}
      </div>
    </OnboardingStep>
  );
};

// ── Screen 3: fit sliders ────────────────────────────────────────────────────
const FitScreen: React.FC = () => {
  const fits = useOnboardingStore((s) => s.fits);
  const setFit = useOnboardingStore((s) => s.setFit);
  return (
    <OnboardingStep
      title="How do you like the fit?"
      subtitle="Untouched sliders stay neutral — Tailor won't assume."
    >
      <div className="flex flex-col gap-[13px]">
        {FIT_SLIDERS.map((sl) => (
          <FitSlider
            key={sl.key}
            label={sl.label}
            minLabel={sl.min}
            maxLabel={sl.max}
            value={fits[sl.key]}
            onChange={(n) => setFit(sl.key, n)}
          />
        ))}
        <div className="mt-1 flex items-center gap-2">
          <Spark size={12} />
          <span className="text-[12px] leading-relaxed" style={{ color: M.ghost }}>
            Fit learns from swaps and feedback later — this is just a starting point.
          </span>
        </div>
      </div>
    </OnboardingStep>
  );
};

// ── Screen 4: taste deck ─────────────────────────────────────────────────────
const TasteScreen: React.FC = () => {
  const department = useOnboardingStore((s) => s.department) ?? 'womens';
  const addSwipe = useOnboardingStore((s) => s.addSwipe);
  const swipedCount = useOnboardingStore((s) => s.tasteSwipes.length);
  return (
    <OnboardingStep
      title="This you?"
      subtitle="Like what you'd wear, pass on what you wouldn't — the same swipe you'll use on real items."
    >
      <TasteDeck department={department} onSwipe={addSwipe} swipedCount={swipedCount} />
    </OnboardingStep>
  );
};

// ── Screen 5: occasions ──────────────────────────────────────────────────────
const OCCASIONS: { key: string; label: string }[] = [
  { key: 'office', label: 'Office' },
  { key: 'casual_work', label: 'Casual work' },
  { key: 'going_out', label: 'Going out' },
  { key: 'athletic', label: 'Athletic' },
  { key: 'home', label: 'Home / errands' },
  { key: 'events', label: 'Events' },
];

const OccasionsScreen: React.FC = () => {
  const occasions = useOnboardingStore((s) => s.occasions);
  const toggleOccasion = useOnboardingStore((s) => s.toggleOccasion);
  return (
    <OnboardingStep
      title="Where does your week take you?"
      subtitle="Pick all that apply — outfits follow your calendar, not a catalog."
    >
      <div className="flex flex-wrap gap-2.5">
        {OCCASIONS.map((o) => {
          const active = occasions.includes(o.key);
          return (
            <Chip
              key={o.key}
              active={active}
              onClick={() => toggleOccasion(o.key)}
              icon={active ? <Check size={13} strokeWidth={3} /> : null}
            >
              {o.label}
            </Chip>
          );
        })}
      </div>
      {occasions.length > 0 ? (
        <div className="mt-[22px] flex items-center gap-2">
          <Spark size={12} />
          <span className="text-[12px]" style={{ color: M.ghost }}>
            {occasions.length} picked — that&rsquo;s plenty to start.
          </span>
        </div>
      ) : null}
    </OnboardingStep>
  );
};

// ── Screen 6: weather permission + closet seed ───────────────────────────────
type GeoStatus = 'idle' | 'requesting' | 'granted' | 'denied' | 'unsupported';

const WeatherScreen: React.FC = () => {
  const router = useRouter();
  const location = useOnboardingStore((s) => s.location);
  const setLocation = useOnboardingStore((s) => s.setLocation);
  const setCompleted = useOnboardingStore((s) => s.setCompleted);

  const [geo, setGeo] = useState<GeoStatus>(location ? 'granted' : 'idle');
  const [busy, setBusy] = useState<null | 'gmail' | 'photo'>(null);
  const [error, setError] = useState<string | null>(null);
  const committedRef = useRef(false);

  const requestLocation = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeo('unsupported');
      return;
    }
    setGeo('requesting');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        // Coords only, coarsened to ~1km — enough for a local forecast, not a
        // precise location. Matches the weather_cache lat/lon/timezone shape.
        const round = (n: number) => Math.round(n * 100) / 100;
        let timezone: string | undefined;
        try {
          timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        } catch {
          timezone = undefined;
        }
        setLocation({ lat: round(pos.coords.latitude), lon: round(pos.coords.longitude), timezone });
        setGeo('granted');
      },
      () => setGeo('denied'),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  };

  // Closet-seed handoff. The shared Gmail/photo flows are fired UNCHANGED; we just
  // commit the staged answers first (Gmail does a full-page redirect that would
  // wipe the in-memory store, and either way we want onboarding marked done so the
  // gate lets the user back in). seedOnboarding is idempotent, so this never
  // conflicts with the shell's Finish commit.
  const commitThen = async (kind: 'gmail' | 'photo', go: () => void | Promise<void>) => {
    setError(null);
    setBusy(kind);
    try {
      if (!committedRef.current) {
        await seedOnboarding(useOnboardingStore.getState().buildSeedPayload());
        committedRef.current = true;
        setCompleted(true);
      }
      await go();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
      setBusy(null);
    }
  };

  return (
    <OnboardingStep
      title="Dress for the sky"
      subtitle="One rough location check a day powers weather-aware outfits."
    >
      <div className="min-h-0 flex-1 space-y-[18px] overflow-y-auto pb-2">
        {/* Weather permission */}
        {geo === 'granted' ? (
          <div
            className="flex items-center justify-center gap-2 rounded-full text-[14px] font-semibold"
            style={{ height: 52, background: 'var(--mint)', color: 'var(--brand-teal)' }}
          >
            <Check size={17} strokeWidth={3} /> Location added
          </div>
        ) : geo === 'denied' || geo === 'unsupported' ? (
          // Permission declined / unavailable — calm fallback (PermissionState copy),
          // no dead-end: the user continues without weather and enables it later.
          <div style={{ ...M.glass(24), padding: 20, textAlign: 'center' }}>
            <div className="flex justify-center">
              <Medallion tone="amber" size={64} icon={<MapPin size={24} />} />
            </div>
            <div className="mt-4 text-[15px] font-semibold text-white">
              {geo === 'denied' ? 'Location is off' : "Location isn't available"}
            </div>
            <p
              className="mx-auto mt-1.5 max-w-[248px] text-[12.5px] leading-relaxed"
              style={{ color: M.faint }}
            >
              {geo === 'denied'
                ? 'No problem — weather-aware picks stay optional. You can enable this later in Settings.'
                : "This device can't share a location. You can enable weather later in Settings."}
            </p>
          </div>
        ) : (
          <div style={{ ...M.glass(24), padding: 22, textAlign: 'center' }}>
            <div className="flex justify-center">
              <Medallion tone="mint" pulse size={72} icon={<MapPin size={26} />} />
            </div>
            <div className="mt-4 text-[15.5px] font-semibold text-white">Approximate only</div>
            <p
              className="mx-auto mt-1.5 max-w-[240px] text-[12.5px] leading-relaxed"
              style={{ color: M.faint }}
            >
              City-level, never stored as a trail. Coordinates only — no address, no tracking.
            </p>
            <button
              type="button"
              onClick={requestLocation}
              disabled={geo === 'requesting'}
              className="mt-4 text-[13px] font-semibold disabled:opacity-60"
              style={{ color: 'var(--mint)' }}
            >
              {geo === 'requesting' ? 'Waiting for permission…' : 'Use my location'}
            </button>
          </div>
        )}

        {/* Closet seed */}
        <section>
          <div
            className="mb-2 flex items-center gap-2 rounded-[20px]"
            style={{
              padding: '15px 17px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.09)',
            }}
          >
            <Spark size={15} />
            <div className="flex-1">
              <div className="text-[13.5px] font-semibold text-white">Next: seed your closet</div>
              <div className="mt-0.5 text-[12px]" style={{ color: M.faint }}>
                Gmail receipts or a few photos — Tailor does the rest.
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-2.5">
            <ClosetCta
              icon={<GmailGlyph size={22} />}
              title="Connect Gmail"
              hint="Import receipts into your closet"
              busy={busy === 'gmail'}
              disabled={busy !== null}
              onClick={() => commitThen('gmail', () => startGmailConnect())}
            />
            <ClosetCta
              icon={<Camera size={20} color="var(--mint)" />}
              title="Upload photos"
              hint="Add pieces from a photo"
              busy={busy === 'photo'}
              disabled={busy !== null}
              onClick={() => commitThen('photo', () => router.push('/add-photo'))}
            />
          </div>
          {error ? (
            <p className="mt-2 text-[12.5px]" style={{ color: 'var(--danger)' }}>
              {error}
            </p>
          ) : null}
          <p className="mt-3 text-[12.5px]" style={{ color: M.ghost }}>
            Or skip — you can build your closet anytime from the app.
          </p>
        </section>
      </div>
    </OnboardingStep>
  );
};

function ClosetCta({
  icon,
  title,
  hint,
  busy,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center gap-3 text-left transition-colors disabled:opacity-60"
      style={{
        padding: '14px 16px',
        borderRadius: 20,
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.11)',
      }}
    >
      <span
        className="flex shrink-0 items-center justify-center rounded-xl"
        style={{ width: 40, height: 40, background: 'rgba(255,255,255,0.07)' }}
      >
        {icon}
      </span>
      <span className="flex-1">
        <span className="block text-[15px] font-semibold text-white">{title}</span>
        <span className="block text-[12.5px]" style={{ color: M.faint }}>
          {hint}
        </span>
      </span>
      {busy ? (
        <span
          className="h-4 w-4 rounded-full border-2 border-white/30"
          style={{ borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.7s linear infinite' }}
          aria-hidden
        />
      ) : (
        <ChevronRight size={18} style={{ color: M.faint }} />
      )}
    </button>
  );
}

export const STEPS: StepDef[] = [
  {
    key: 'departments',
    title: 'Departments',
    skippable: false,
    Component: DepartmentsScreen,
    isComplete: (s) => !!s.department,
  },
  {
    key: 'sizes',
    title: 'Sizes',
    skippable: false,
    Component: SizesScreen,
    // Top + bottom are the fit-critical anchors; shoe/dress stay optional.
    isComplete: (s) => !!s.sizes.top && !!s.sizes.bottom,
  },
  {
    key: 'fits',
    title: 'Fit',
    skippable: true,
    Component: FitScreen,
    isComplete: (s) => s.fits.top !== undefined && s.fits.bottom !== undefined,
  },
  {
    key: 'taste',
    title: 'Taste',
    skippable: true,
    Component: TasteScreen,
    isComplete: (s) => s.tasteSwipes.length >= 5,
  },
  {
    key: 'occasions',
    title: 'Occasions',
    skippable: true,
    Component: OccasionsScreen,
    isComplete: (s) => s.occasions.length >= 1,
  },
  {
    key: 'weather',
    title: 'Weather',
    skippable: true,
    Component: WeatherScreen,
    isComplete: (s) => !!s.location,
  },
];
