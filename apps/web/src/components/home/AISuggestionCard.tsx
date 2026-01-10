import { Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';

interface AISuggestionCardProps {
  suggestion?: string;
  className?: string;
}

export function AISuggestionCard({ 
  suggestion = "Layered look + boots",
  className
}: AISuggestionCardProps) {
  return (
    <div 
      className={cn(
        "flex items-center gap-4 h-[91px] px-[20px] py-[20px] w-full relative overflow-hidden",
        "rounded-[24px]",
        "border border-white/20",
        "shadow-[0_25px_25px_rgba(0,0,0,0.25)]",
        className
      )}
      style={{
        background: 'linear-gradient(90deg, rgba(0, 186, 166, 0.4) 0%, rgba(8, 74, 77, 0.4) 100%)'
      }}
    >
      <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center shrink-0">
        <Sparkles className="w-5 h-5 text-[#4BE2D6]" />
      </div>
      
      <div className="flex flex-col justify-center gap-0.5">
        <span className="text-sm text-white/90 font-medium">AI Suggests</span>
        <span className="text-lg font-bold text-white leading-tight">
          {suggestion}
        </span>
      </div>
    </div>
  );
}
