import React from "react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen w-full relative overflow-hidden">
        {/* Layer A: Background Image - "closet" */}
        {/* Note: This requires 'closet-bg.jpg' in public/auth/ */}
        <div 
            className="absolute inset-0 z-0 bg-primary/20" // Fallback color
            style={{
                backgroundImage: "url('/auth/closet-bg.jpg')",
                backgroundSize: "cover",
                backgroundPosition: "center",
            }}
        />

        {/* Layer B: Overlay - "black blur" */}
        {/* Matches "black blur" layer: dark overlay with blur effect */}
        <div className="absolute inset-0 z-0 bg-black/60 backdrop-blur-[10px]" />
        
        {/* Logo - centered horizontally, positioned at Y: 32 */}
        <img 
            src="/auth/white-logo.jpg" 
            alt="Tailor" 
            className="absolute left-1/2 -translate-x-1/2 top-[32px] z-10 w-[228px] h-[228px] object-contain"
        />
        
        {/* Forms Container - positioned at X: 24, Y: 232 */}
        <div className="absolute left-[24px] top-[232px] z-10 w-[calc(100%-48px)] max-w-md">
            {children}
        </div>
    </div>
  );
}
