import React from "react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen w-full relative overflow-hidden">
      {/* Layer A: background image ("closet"), with a brand-teal fallback tint */}
      <div
        className="absolute inset-0 z-0"
        style={{
          backgroundColor: "rgba(8, 75, 77, 0.2)",
          backgroundImage: "url('/auth/closet-bg.jpg')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />

      {/* Layer B: darkening scrim */}
      <div
        className="absolute inset-0 z-0"
        style={{ background: "var(--grad-scrim)" }}
      />

      {/* Content: vertically-centered, scrollable flex column */}
      <div
        className="relative z-10 min-h-screen flex flex-col items-stretch justify-center"
        style={{ padding: "60px 24px 28px", overflowY: "auto" }}
      >
        {children}
      </div>
    </div>
  );
}
