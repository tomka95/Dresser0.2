'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Icon, type IconName } from '@/components/ds/Icon';
import { StylistMark } from '@/components/ds/StylistMark';
import { M, NAV_CLEAR } from '@/components/ds/materials';

// Bottom padding so page content scrolls clear of the floating nav.
export { NAV_CLEAR };

interface BottomNavBarProps {
  /** Route to highlight; derived from usePathname() when omitted. */
  activeRoute?: string;
}

const TABS: { href: string; icon: IconName; label: string }[] = [
  { href: '/home', icon: 'NavigationHouse02', label: 'Home' },
  { href: '/search', icon: 'InterfaceSearchMagnifyingGlass', label: 'Search' },
  { href: '/closet', icon: 'Wardrobe', label: 'Closet' },
  { href: '/profile', icon: 'UserUser01', label: 'Profile' },
];

/**
 * §0 · G1 — Floating glass nav. A deep-glass pill detached 18px off the bottom
 * edge with 16px side insets; four tabs (Home / Search · Closet / Profile — the
 * Closet tab uses the wardrobe glyph) and a center hanger FAB that opens the AI
 * Stylist chat. Content scrolls beneath — pad scrolling pages with NAV_CLEAR.
 */
export function BottomNavBar({ activeRoute }: BottomNavBarProps) {
  const pathname = usePathname();
  const active = activeRoute ?? pathname ?? '';
  const isActive = (route: string) => active === route || active.startsWith(`${route}/`);
  const fabActive = isActive('/chat');

  const Tab = ({ href, icon, label }: (typeof TABS)[number]) => {
    const on = isActive(href);
    return (
      <Link
        href={href}
        aria-label={label}
        aria-current={on ? 'page' : undefined}
        className="relative flex flex-col items-center justify-center active:scale-[0.88]"
        style={{
          width: 56,
          height: 46,
          borderRadius: 16,
          gap: 2,
          color: on ? '#fff' : 'rgba(255,255,255,0.52)',
          background: on ? 'rgba(255,255,255,0.10)' : 'transparent',
          transition: 'all 260ms var(--spring)',
        }}
      >
        <Icon name={icon} size={23} />
        {on && (
          <span
            className="font-accent"
            style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.02em' }}
          >
            {label}
          </span>
        )}
        {on && (
          <span
            className="absolute rounded-full"
            style={{
              top: 5,
              right: 9,
              width: 4,
              height: 4,
              background: 'var(--mint)',
              boxShadow: '0 0 8px var(--mint)',
            }}
            aria-hidden
          />
        )}
      </Link>
    );
  };

  return (
    <div className="pointer-events-none fixed bottom-[18px] left-0 right-0 z-40 mx-auto w-full max-w-[430px] px-4">
      <div className="pointer-events-auto relative">
        {/* Center FAB — AI Stylist (chat) entry, hanger mark, seated level with the tabs. */}
        <div
          className="absolute left-1/2 z-[2]"
          style={{
            top: 3,
            transform: `translateX(-50%)${fabActive ? ' translateY(-2px)' : ''}`,
            transition: 'transform 300ms var(--spring)',
          }}
        >
          {fabActive && (
            <span
              data-t2-anim
              className="absolute rounded-full"
              style={{
                inset: -5,
                border: '1.5px solid rgba(75,226,214,0.5)',
                animation: 't2-ring 1.8s ease-out infinite',
              }}
              aria-hidden
            />
          )}
          <Link
            href="/chat"
            aria-label="AI Stylist chat"
            aria-current={fabActive ? 'page' : undefined}
            className="relative flex items-center justify-center rounded-full active:scale-90"
            style={{
              width: 58,
              height: 58,
              color: fabActive ? 'var(--mint)' : '#fff',
              background: fabActive
                ? 'linear-gradient(165deg, #0e5a54, #0a3633)'
                : 'linear-gradient(165deg, #147f74, #0a3633)',
              border: fabActive
                ? '1.5px solid rgba(75,226,214,0.65)'
                : '1px solid rgba(255,255,255,0.18)',
              boxShadow: fabActive
                ? '0 8px 22px -6px rgba(10,54,51,0.8), 0 0 22px rgba(75,226,214,0.35), inset 0 1px 0 rgba(255,255,255,0.2)'
                : '0 8px 22px -6px rgba(4,26,25,0.7), inset 0 1px 0 rgba(255,255,255,0.22)',
              transition: 'all 300ms var(--spring)',
            }}
          >
            <StylistMark size={27} />
          </Link>
        </div>

        {/* Glass pill bar */}
        <nav
          aria-label="Main navigation"
          className={cn('flex items-center justify-between')}
          style={{ ...M.deep(999), height: 64, padding: '0 24px' }}
        >
          <div className="flex" style={{ gap: 2 }}>
            <Tab {...TABS[0]} />
            <Tab {...TABS[1]} />
          </div>
          {/* FAB seat */}
          <div style={{ width: 58 }} aria-hidden />
          <div className="flex" style={{ gap: 2 }}>
            <Tab {...TABS[2]} />
            <Tab {...TABS[3]} />
          </div>
        </nav>
      </div>
    </div>
  );
}
