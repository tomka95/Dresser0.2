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
      <body>
        <nav className="border-b">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <Link href="/" className="text-xl font-bold">
                Dresser
              </Link>
              <div className="flex gap-6">
                <Link
                  href="/closet"
                  className="text-sm font-medium hover:text-gray-600"
                >
                  Closet
                </Link>
                <Link
                  href="/outfits"
                  className="text-sm font-medium hover:text-gray-600"
                >
                  Outfits
                </Link>
              </div>
            </div>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}



