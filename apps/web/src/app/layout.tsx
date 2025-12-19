import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Tailor - AI Closet / Stylist',
  description: 'Your AI-powered closet and outfit stylist',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="flex justify-center min-h-screen" style={{ backgroundColor: '#eeede9' }}>
        <div className="w-full max-w-[430px] min-h-screen relative shadow-2xl overflow-hidden" style={{ backgroundColor: '#eeede9' }}>
          <main className="h-full overflow-y-auto scrollbar-hide">
            {children}
          </main>
          </div>
      </body>
    </html>
  );
}



