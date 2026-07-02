import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { HangerImg } from '@/components/ds';

/** 404 in the dark app theme — "This rack is empty" + the brand hanger mark. */
export default function NotFound() {
  return (
    <AppShell scroll={false}>
      <div className="flex h-full flex-col items-center justify-center px-7 text-center">
        <div className="text-[96px] font-extrabold leading-none tracking-[-2px] text-white">404</div>
        <div className="mb-1 mt-2">
          <HangerImg w={150} />
        </div>
        <h2 className="m-0 mb-2.5 text-[22px] font-bold text-white">This rack is empty</h2>
        <p className="mx-auto mb-[26px] max-w-[280px] text-[14.5px] leading-relaxed text-white/[0.65]">
          The page you&rsquo;re looking for doesn&rsquo;t exist or has moved.
        </p>
        <Link
          href="/home"
          className="inline-flex h-12 items-center justify-center rounded-full bg-white px-7 text-[16px] font-medium"
          style={{ color: 'var(--brand-teal)' }}
        >
          Back to home
        </Link>
      </div>
    </AppShell>
  );
}
