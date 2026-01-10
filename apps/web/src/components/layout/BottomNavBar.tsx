import { Home, Bookmark, MessageCircle, User } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface BottomNavBarProps {
  activeRoute?: string;
}

export function BottomNavBar({ activeRoute = '/closet' }: BottomNavBarProps) {
  return (
    <div className="fixed bottom-0 left-0 right-0 bg-black pb-0 pt-2 px-6 z-50 rounded-t-[20px] max-w-[430px] mx-auto">
      <div className="flex items-center justify-between mb-0 py-4"> {/* Added py-4 to give height to the bar itself */}
        {/* Home -> /closet since that's the main app view */}
        <Link href="/closet" className="flex flex-col items-center gap-1">
          <Home className={cn("w-7 h-7", activeRoute === '/closet' ? "text-white" : "text-white/60")} />
        </Link>
        
        <Link href="/outfits" className="flex flex-col items-center gap-1">
          <Bookmark className={cn("w-7 h-7", activeRoute === '/outfits' ? "text-white" : "text-white/60")} />
        </Link>

        {/* FAB Wrapper - Height 0 to not affect bar height */}
        <div className="relative w-[110px] h-0">
          <button 
            className="absolute left-0 -top-[82px] w-[110px] h-[110px] rounded-full flex items-center justify-center shadow-lg transition-transform hover:scale-105 active:scale-95"
            style={{
              background: 'linear-gradient(180deg, rgb(10, 54, 51) 0%, rgb(10, 99, 102) 100%)'
            }}
          >
            {/* Custom Hanger Icon */}
            <img 
              src="/images/colav.jpg" 
              alt="Add Outfit" 
              className="w-22 h-22 object-contain"
            />
          </button>
        </div>

        <Link href="/chat" className="flex flex-col items-center gap-1">
          <MessageCircle className={cn("w-7 h-7", activeRoute === '/chat' ? "text-white" : "text-white/60")} />
        </Link>

        <Link href="/profile" className="flex flex-col items-center gap-1">
          <User className={cn("w-7 h-7", activeRoute === '/profile' ? "text-white" : "text-white/60")} />
        </Link>
      </div>
    </div>
  );
}
