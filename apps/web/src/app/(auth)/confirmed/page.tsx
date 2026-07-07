"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Btn, SuccessPop, Spark, M } from "@/components/ds";
import { getSessionUser } from "@/lib/auth";
import { getOnboardingStatus } from "@/lib/api/onboarding";

/**
 * Email confirmed (§1 · A7) — celebratory landing after /auth/callback
 * (?next=/confirmed). Full-screen success pop (no glass card), then "Get started"
 * routes into the app by onboarding state.
 */
export default function ConfirmedPage() {
  const router = useRouter();
  const [firstName, setFirstName] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    getSessionUser().then((user) => {
      const full = (user?.user_metadata as { full_name?: string } | undefined)?.full_name;
      if (full) setFirstName(full.trim().split(/\s+/)[0]);
    });
  }, []);

  // Route by onboarding state: a fresh signup is definitionally not onboarded and
  // lands in /onboarding; a re-confirmed returning user goes straight home. Fail
  // closed to /onboarding if status can't be read (the gate would bounce anyway).
  async function handleStart() {
    setStarting(true);
    try {
      const { completed } = await getOnboardingStatus();
      router.replace(completed ? "/home" : "/onboarding");
    } catch {
      router.replace("/onboarding");
    }
  }

  return (
    <div className="flex flex-col items-center px-2.5 text-center">
      <SuccessPop size={104} />
      <h1
        className="m-0 mt-[26px] text-white"
        style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.7px" }}
      >
        {firstName ? `You're in, ${firstName}` : "You're in"}
      </h1>
      <p
        className="mx-auto mt-[9px] max-w-[260px]"
        style={{ color: M.soft, fontSize: 15, lineHeight: 1.55 }}
      >
        Email confirmed. Let&rsquo;s meet your closet — <Spark size={13} /> Tailor styles from what
        you own.
      </p>
      <div className="mt-7" style={{ minWidth: 220 }}>
        <Btn variant="primary" size="lg" fullWidth pending={starting} onClick={handleStart}>
          Get started
        </Btn>
      </div>
      <p className="mt-3.5" style={{ color: M.ghost, fontSize: 12.5 }}>
        ~2 minutes to set up
      </p>
    </div>
  );
}
