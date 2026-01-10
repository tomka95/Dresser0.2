import { Cloud } from 'lucide-react';
import { cn } from '@/lib/utils';

interface WeatherCalendarCardProps {
  temperature?: number;
  time?: string;
  event?: string;
  className?: string;
}

export function WeatherCalendarCard({ 
  temperature = 21,
  time = "10:00",
  event = "Meeting with Guy",
  className
}: WeatherCalendarCardProps) {
  return (
    <div 
      className={cn(
        "flex items-center h-[91px] px-[20px] w-full relative overflow-hidden",
        "rounded-[24px]",
        "border border-white/20",
        "shadow-[0_25px_25px_rgba(0,0,0,0.25)]",
        className
      )}
      style={{
        background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.15) 0%, rgba(255, 255, 255, 0.05) 100%)'
      }}
    >
      {/* Weather Section */}
      <div className="flex items-center gap-3 pr-4">
        <Cloud className="w-8 h-8 text-white" />
        <div className="flex items-start">
          <span className="text-4xl font-bold text-white leading-none tracking-tight">{temperature}</span>
          <span className="text-lg font-medium text-white mt-1 ml-0.5">°C</span>
        </div>
      </div>

      {/* Vertical Divider */}
      <div className="w-[1px] h-10 bg-white/20 mx-4" />

      {/* Calendar Section */}
      <div className="flex flex-col justify-center gap-0.5">
        <span className="text-sm font-medium text-white/90 leading-tight">{time}</span>
        <span className="text-lg font-bold text-white leading-tight truncate max-w-[150px]">
          {event}
        </span>
      </div>
    </div>
  );
}
