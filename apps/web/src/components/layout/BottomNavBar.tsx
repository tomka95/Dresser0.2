import { Home, Search, MessageCircle, User } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface BottomNavBarProps {
  activeRoute?: string;
}

export function BottomNavBar({ activeRoute }: BottomNavBarProps) {
  const isActive = (route: string) => activeRoute === route;

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-black pb-0 pt-2 px-6 z-50 rounded-t-[20px] max-w-[430px] mx-auto">
      <div className="flex items-center justify-between mb-0 py-4">
        {/* Home -> /home */}
        <Link href="/home" className="flex flex-col items-center gap-1">
          <Home className={cn("w-7 h-7", isActive('/home') ? "text-white" : "text-white/60")} />
        </Link>
        
        <Link href="/search" className="flex flex-col items-center gap-1">
          <Search className={cn("w-7 h-7", isActive('/search') ? "text-white" : "text-white/60")} />
        </Link>

        {/* FAB Wrapper - Center green button navigates to /closet */}
        <div className="relative w-[110px] h-0">
          <Link 
            href="/closet"
            className="absolute left-0 -top-[82px] w-[110px] h-[110px] rounded-full flex items-center justify-center shadow-lg transition-transform hover:scale-105 active:scale-95"
            style={{
              background: isActive('/closet') 
                ? 'linear-gradient(180deg, rgb(10, 54, 51) 0%, rgb(10, 99, 102) 100%)'
                : 'linear-gradient(180deg, rgb(10, 54, 51) 0%, rgb(10, 99, 102) 100%)'
            }}
          >
            {/* Custom Hanger Icon */}
            <img 
              src="/images/colav.jpg" 
              alt="Closet" 
              className="w-22 h-22 object-contain"
            />
          </Link>
        </div>

        <Link href="/chat" className="flex flex-col items-center gap-1">
          <MessageCircle className={cn("w-7 h-7", isActive('/chat') ? "text-white" : "text-white/60")} />
        </Link>

        <Link href="/profile" className="flex flex-col items-center gap-1">
          <User className={cn("w-7 h-7", isActive('/profile') ? "text-white" : "text-white/60")} />
        </Link>
      </div>
    </div>
  );
}
