import { cn } from '@/lib/utils';
import { ReactNode } from 'react';

interface InfoCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  variant?: 'frosted' | 'solid';
}

export function InfoCard({ children, className, variant = 'frosted', ...props }: InfoCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl p-4 w-full backdrop-blur-md",
        variant === 'frosted' && "bg-white/10 border border-white/20",
        variant === 'solid' && "bg-[#1E8878]",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
