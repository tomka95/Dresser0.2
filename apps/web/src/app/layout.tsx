import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Dresser - AI Closet / Stylist',
  description: 'Your AI-powered closet and outfit stylist',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-neutral-900 flex justify-center min-h-screen">
        <div className="w-full max-w-[430px] min-h-screen bg-background relative shadow-2xl overflow-hidden">
          <main className="h-full overflow-y-auto scrollbar-hide">
            {children}
          </main>
          </div>
      </body>
    </html>
  );
}



