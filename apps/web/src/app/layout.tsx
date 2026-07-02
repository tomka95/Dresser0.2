import type { Metadata } from 'next';
import { Inter, DM_Sans } from 'next/font/google';
import './globals.css';

// Design-system typefaces: Inter (UI) + DM Sans (chips / category labels).
// Exposed as CSS variables consumed by --font-sans / --font-accent in globals.css.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });
const dmSans = DM_Sans({ subsets: ['latin'], variable: '--font-dm-sans', display: 'swap' });

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
    <html lang="en" className={`${inter.variable} ${dmSans.variable}`}>
      <body className="flex justify-center h-screen overflow-hidden" style={{ backgroundColor: '#eeede9' }}>
        <div className="w-full max-w-[430px] h-full relative shadow-2xl overflow-hidden bg-[#eeede9]">
          <main className="h-full overflow-y-auto scrollbar-hide relative">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
