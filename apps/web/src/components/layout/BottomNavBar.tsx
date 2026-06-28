import { Home, Search, MessageCircle, User } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface BottomNavBarProps {
  /** Active tab key: 'home' | 'search' | 'closet' | 'chat' | 'profile'. */
  active?: string;
}

const ICON = 'w-7 h-7';

/** Hanger glyph for the central closet FAB (design uses Icon name="Hanger"). */
function Hanger({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M10.5 5.5A1.8 1.8 0 1 1 13 7.1L12 8" />
      <path d="M12 8 3.6 14.4A1 1 0 0 0 4.2 16.2h15.6a1 1 0 0 0 .6-1.8L12 8Z" />
    </svg>
  );
}

export function BottomNavBar({ active }: BottomNavBarProps) {
  const color = (key: string) => (active === key ? 'text-white' : 'text-white/60');

  return (
    <div
      className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-50"
      style={{
        background: 'var(--pure-black)',
        borderTopLeftRadius: 20,
        borderTopRightRadius: 20,
      }}
    >
      <div className="relative flex items-center justify-between px-6 py-4">
        <Link href="/home" aria-label="Home" className="p-2">
          <Home className={cn(ICON, color('home'))} />
        </Link>

        <Link href="/search" aria-label="Search" className="p-2">
          <Search className={cn(ICON, color('search'))} />
        </Link>

        {/* Center floating closet FAB */}
        <Link
          href="/closet"
          aria-label="Closet"
          className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 flex items-center justify-center transition-transform active:scale-95"
          style={{
            width: 76,
            height: 76,
            borderRadius: '50%',
            border: '4px solid var(--pure-black)',
            background: 'var(--grad-teal)',
            boxShadow: '0 8px 20px rgba(10,54,51,0.5)',
            color: '#fff',
          }}
        >
          <Hanger size={32} />
        </Link>

        <Link href="/chat" aria-label="Chat" className="p-2">
          <MessageCircle className={cn(ICON, color('chat'))} />
        </Link>

        <Link href="/profile" aria-label="Profile" className="p-2">
          <User className={cn(ICON, color('profile'))} />
        </Link>
      </div>
    </div>
  );
}
