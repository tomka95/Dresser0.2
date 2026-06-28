import React from 'react';

interface SectionHeaderProps {
  title: string;
  action?: string;
  onAction?: () => void;
}

/** Dark section header — white title + optional muted action on the right. */
export function SectionHeader({ title, action, onAction }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-white text-[20px] font-semibold m-0">{title}</h2>
      {action &&
        (onAction ? (
          <button
            type="button"
            onClick={onAction}
            className="text-[13px] font-medium"
            style={{ color: 'rgba(255,255,255,0.7)' }}
          >
            {action}
          </button>
        ) : (
          <span className="text-[13px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
            {action}
          </span>
        ))}
    </div>
  );
}
