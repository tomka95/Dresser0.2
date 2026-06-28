'use client';

import React from 'react';

/** Tailor wordmark logo, screen-blended onto the dark scrim. */
export function AuthLogo() {
  return (
    <img
      src="/auth/white-logo.jpg"
      alt="Tailor"
      style={{
        width: 120,
        height: 120,
        objectFit: 'contain',
        margin: '0 auto 12px',
        display: 'block',
        mixBlendMode: 'screen',
      }}
    />
  );
}

/** The frosted glass card that wraps each auth form. */
export function AuthCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        borderRadius: 22,
        background: 'rgba(0,0,0,0.30)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid var(--tr-10)',
        padding: 24,
        boxShadow: 'var(--shadow-lg)',
      }}
    >
      {children}
    </div>
  );
}

type GlassInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  icon?: React.ReactNode;
};

/** A 52px translucent pill input with a leading icon. */
export function GlassInput({ icon, ...inputProps }: GlassInputProps) {
  return (
    <div
      style={{
        height: 52,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '0 18px',
        borderRadius: 999,
        background: 'var(--tr-10)',
        boxShadow: 'inset 0 0 0 1px var(--tr-20)',
      }}
    >
      {icon ? (
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            color: 'rgba(255,255,255,0.7)',
            flexShrink: 0,
          }}
        >
          {icon}
        </span>
      ) : null}
      <input
        {...inputProps}
        style={{
          flex: 1,
          minWidth: 0,
          background: 'transparent',
          border: 'none',
          outline: 'none',
          color: '#ffffff',
          fontSize: 15,
          ...inputProps.style,
        }}
      />
    </div>
  );
}

/** A hairline "Or" separator. */
export function OrDivider() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        margin: '16px 0',
      }}
    >
      <div style={{ flex: 1, height: 1, background: 'var(--tr-20)' }} />
      <span
        style={{
          color: 'rgba(255,255,255,0.5)',
          fontSize: 11,
          letterSpacing: '.5px',
          textTransform: 'uppercase',
        }}
      >
        Or
      </span>
      <div style={{ flex: 1, height: 1, background: 'var(--tr-20)' }} />
    </div>
  );
}

type ProviderButtonProps = {
  icon?: React.ReactNode;
  children: React.ReactNode;
  onClick?: () => void;
  type?: 'button' | 'submit';
};

/** An outlined social-provider pill button. */
export function ProviderButton({
  icon,
  children,
  onClick,
  type = 'button',
}: ProviderButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      style={{
        width: '100%',
        height: 48,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        borderRadius: 999,
        background: 'transparent',
        border: '1px solid var(--tr-20)',
        color: '#ffffff',
        fontSize: 15,
        fontWeight: 600,
        cursor: 'pointer',
      }}
    >
      {icon}
      {children}
    </button>
  );
}

/** The Google "G" mark. */
export function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48">
      <path
        fill="#4285F4"
        d="M45.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h11.8c-.5 2.7-2 5-4.4 6.6v5.5h7.1c4.1-3.8 6.6-9.4 6.6-16.1z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.9 0 10.9-2 14.5-5.4l-7.1-5.5c-2 1.3-4.5 2.1-7.4 2.1-5.7 0-10.5-3.8-12.2-9H4.5v5.7C8.1 41.1 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.8 28.2c-.4-1.3-.7-2.7-.7-4.2s.3-2.9.7-4.2v-5.7H4.5C3 17.1 2.1 20.4 2.1 24s.9 6.9 2.4 9.9l7.3-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.8c3.2 0 6.1 1.1 8.4 3.3l6.3-6.3C34.9 4.1 29.9 2 24 2 15.4 2 8.1 6.9 4.5 14.1l7.3 5.7c1.7-5.2 6.5-9 12.2-9z"
      />
    </svg>
  );
}

/** The Apple mark. */
export function AppleA() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="#fff">
      <path d="M17.05 12.5c-.03-2.6 2.12-3.85 2.22-3.9-1.21-1.77-3.1-2.01-3.76-2.04-1.6-.16-3.12.94-3.93.94-.81 0-2.06-.92-3.39-.9-1.74.03-3.35 1.01-4.25 2.57-1.81 3.15-.46 7.8 1.3 10.35.86 1.25 1.88 2.65 3.22 2.6 1.29-.05 1.78-.83 3.34-.83 1.55 0 2 .83 3.36.81 1.39-.03 2.27-1.27 3.12-2.52.98-1.44 1.39-2.84 1.41-2.91-.03-.01-2.71-1.04-2.74-4.12zM14.6 4.84c.71-.86 1.19-2.06 1.06-3.25-1.02.04-2.27.68-3 1.54-.66.76-1.23 1.98-1.08 3.15 1.14.09 2.31-.58 3.02-1.44z" />
    </svg>
  );
}
