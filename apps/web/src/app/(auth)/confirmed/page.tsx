"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";
import { DSButton } from "@/components/ds";
import { getSessionUser } from "@/lib/auth";

/**
 * Email confirmed — celebratory landing after /auth/callback (?next=/confirmed).
 * Full-screen success (no glass card), then "Get started" into the app.
 */
export default function ConfirmedPage() {
  const router = useRouter();
  const [firstName, setFirstName] = useState<string | null>(null);

  useEffect(() => {
    getSessionUser().then((user) => {
      const full = (user?.user_metadata as { full_name?: string } | undefined)?.full_name;
      if (full) setFirstName(full.trim().split(/\s+/)[0]);
    });
  }, []);

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-2 text-center">
      <div
        className="mx-auto mb-[22px] mt-1 flex items-center justify-center rounded-full"
        style={{ width: 72, height: 72, background: "rgba(75,226,214,0.18)", color: "var(--mint)" }}
      >
        <Check size={34} strokeWidth={2.4} />
      </div>
      <h1 className="m-0 mb-2.5 text-[28px] font-bold tracking-[-0.4px] text-white">
        {firstName ? `You're in, ${firstName}` : "You're in"}
      </h1>
      <p className="mx-auto mb-7 max-w-[290px] text-[15px] leading-relaxed text-white/70">
        Your account is confirmed. Let&rsquo;s build your closet.
      </p>
      <div className="w-full max-w-[320px]">
        <DSButton variant="light" fullWidth pill onClick={() => router.push("/home")}>
          Get started
        </DSButton>
      </div>
    </div>
  );
}
