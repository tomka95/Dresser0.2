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

        {/* Layer B: Overlay - "black blur" (darkening gradient, NO blur) */}
        <div 
            className="absolute inset-0 z-0" 
            style={{
                background: 'linear-gradient(180deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.6) 50%, rgba(0,0,0,0.9) 100%)'
            }}
        />
        
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
