import React from 'react';
import { LightButton } from './LightButton';

interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  body: string;
  ctaLabel?: string;
  ctaIcon?: React.ReactNode;
  onCta?: () => void;
}

/** Centered empty-state block: icon disc + title + body + optional CTA. */
export function EmptyState({ icon, title, body, ctaLabel, ctaIcon, onCta }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center text-center px-4">
      <div
        className="flex items-center justify-center mb-[22px]"
        style={{
          width: 96,
          height: 96,
          borderRadius: '50%',
          background: 'var(--tr-10)',
          border: '1px solid var(--tr-20)',
          color: 'rgba(255,255,255,0.85)',
        }}
      >
        {icon}
      </div>
      <h2 className="text-white text-[22px] font-bold m-0 mb-2.5" style={{ letterSpacing: '-0.3px' }}>
        {title}
      </h2>
      <p
        className="mx-auto mb-6 text-[14.5px] leading-relaxed"
        style={{ color: 'rgba(255,255,255,0.65)', maxWidth: 280 }}
      >
        {body}
      </p>
      {ctaLabel && (
        <LightButton leftIcon={ctaIcon} onClick={onCta} style={{ height: 48, padding: '0 26px' }}>
          {ctaLabel}
        </LightButton>
      )}
    </div>
  );
}
