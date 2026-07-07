import React from "react";

/**
 * Auth shell (§1 redesign · AuthShell) — a full-bleed closet photo under a dark
 * scrim, with the white Tailor wordmark centered above a glass-card column.
 * The column is vertically centered and scrolls if a state runs tall. Stays a
 * server component (no client hooks here); the pages inside are the client parts.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative h-full min-h-full w-full overflow-hidden" style={{ background: "var(--app-bg)" }}>
      {/* Background closet photo */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage: "url('/auth/closet-bg.jpg')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
        aria-hidden
      />
      {/* Scrim gradient — darkens top and bottom so the card + logo read clearly */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          background:
            "linear-gradient(180deg, rgba(4,9,9,0.78) 0%, rgba(4,9,9,0.60) 46%, rgba(4,9,9,0.90) 100%)",
        }}
        aria-hidden
      />

      {/* Content column — white wordmark + card, vertically centered, scrolls if needed */}
      <div
        className="absolute inset-0 z-10 flex flex-col justify-center overflow-y-auto scrollbar-hide"
        style={{ padding: "64px 20px 110px" }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/auth/white-logo.jpg"
          alt="Tailor"
          className="mx-auto mb-4 block h-[220px] w-[220px] object-contain mix-blend-screen"
        />
        {children}
      </div>
    </div>
  );
}
