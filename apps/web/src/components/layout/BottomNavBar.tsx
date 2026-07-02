'use client';

import Link from 'next/link';
import { cn } from '@/lib/utils';
import { Icon, type IconName } from '@/components/ds';

interface BottomNavBarProps {
  activeRoute?: string;
}

const TABS: { href: string; icon: IconName; label: string }[] = [
  { href: '/home', icon: 'NavigationHouse02', label: 'Home' },
  { href: '/search', icon: 'InterfaceSearchMagnifyingGlass', label: 'Search' },
  { href: '/chat', icon: 'CommunicationChatCircle', label: 'Chat' },
  { href: '/profile', icon: 'UserUser01', label: 'Profile' },
];

/**
 * Tailor bottom navigation — black rounded-top bar with four tabs and a large
 * central floating teal "closet" FAB (the brand hanger mark, public/9.png).
 */
export function BottomNavBar({ activeRoute }: BottomNavBarProps) {
  const isActive = (route: string) => activeRoute === route;

  const Tab = ({ href, icon, label }: (typeof TABS)[number]) => (
    <Link
      href={href}
      aria-label={label}
      className={cn(
        'flex items-center justify-center p-2 transition-colors duration-150',
        isActive(href) ? 'text-white' : 'text-white/60 hover:text-white/80',
      )}
    >
      <Icon name={icon} size={28} />
    </Link>
  );

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 mx-auto w-full max-w-[430px]"
      style={{
        background: 'var(--app-nav-bg)',
        borderTopLeftRadius: 20,
        borderTopRightRadius: 20,
        padding: '16px 24px',
      }}
    >
      <div className="relative flex items-center justify-between">
        <Tab {...TABS[0]} />
        <Tab {...TABS[1]} />

        {/* Center FAB — overlaps the bar top edge; navigates to the closet. */}
        <Link
          href="/closet"
          aria-label="Open closet"
          className="absolute left-1/2 flex items-center justify-center rounded-full transition-transform active:scale-95"
          style={{
            top: -16, // bar padding offset: center sits on the bar's top edge
            transform: 'translate(-50%, -50%)',
            width: 76,
            height: 76,
            border: '4px solid var(--app-nav-bg)',
            background: 'var(--grad-teal)',
            boxShadow: '0 8px 20px rgba(10,54,51,0.5)',
          }}
        >
          {/* Brand hanger line-art (generous transparent padding — sized up so the
              visible glyph reads ~32px). */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/9.png" alt="" className="pointer-events-none h-16 w-16 object-contain" aria-hidden />
        </Link>

        <Tab {...TABS[2]} />
        <Tab {...TABS[3]} />
      </div>
    </div>
  );
}
