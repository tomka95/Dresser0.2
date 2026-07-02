import React from "react";

/**
 * Auth shell — background closet photo + scrim, logo above a centered glass
 * card column (design: flex column, justify-center, 60/24/28 padding).
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative h-full min-h-full w-full overflow-hidden" style={{ background: "var(--app-bg)" }}>
      {/* Background photo */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage: "url('/auth/closet-bg.jpg')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
        aria-hidden
      />
      {/* Scrim gradient */}
      <div className="pointer-events-none absolute inset-0 z-0" style={{ background: "var(--grad-scrim)" }} aria-hidden />

      {/* Content column — logo + card, vertically centered, scrolls if needed */}
      <div
        className="absolute inset-0 z-10 flex flex-col justify-center overflow-y-auto scrollbar-hide"
        style={{ padding: "60px 24px 28px" }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/auth/white-logo.jpg"
          alt="Tailor"
          className="mx-auto mb-3 block h-[120px] w-[120px] object-contain mix-blend-screen"
        />
        {children}
      </div>
    </div>
  );
}
