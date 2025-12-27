"use client";

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { FloatingClothes } from '@/components/landing/FloatingClothes';
import { GoogleIcon } from '@/components/icons/GoogleIcon';
import { getGoogleOAuthUrl } from '@/config/authConfig';

export default function HomePage() {
  const handleGoogleLogin = () => {
    const url = getGoogleOAuthUrl();
    window.location.href = url;
  };

  return (
    <div className="min-h-screen flex flex-col relative overflow-hidden" style={{ backgroundColor: '#eeede9' }}>
      {/* Background Cloud - extends over header */}
      <div className="absolute inset-0 w-full h-full z-0">
        <FloatingClothes />
      </div>

      {/* Header */}
      <header className="w-full p-6 flex justify-center items-center z-20 relative">
        <img src="/tailor-logo.png" alt="Tailor" className="h-76 w-auto" />
      </header>

      {/* Main Visual */}
      <main className="flex-1 flex flex-col relative z-10" style={{ backgroundColor: 'transparent' }}>
        <div className="flex-1 w-full max-w-md mx-auto relative">
          {/* Spacer to keep icons centered */}
          <div className="h-full flex items-center justify-center">
          </div>
        </div>
        
        <div className="text-center px-6 mt-[-20px] z-20 relative" style={{ backgroundColor: 'transparent' }}>
          <h2 className="text-3xl font-bold mb-2 text-gray-900">Your Style, AI Powered</h2>
          <p className="text-gray-600">
            Organize your closet and discover new outfits instantly.
        </p>
        </div>
      </main>

      {/* Actions */}
      <footer className="w-full p-6 flex flex-col gap-3 z-10 max-w-md mx-auto pb-10">
        <div className="flex gap-3">
          <Link href="/signup" className="flex-1">
            <Button 
              className="w-full text-lg font-medium h-12 rounded-xl bg-white text-black hover:bg-gray-200"
          >
              Sign Up
            </Button>
          </Link>
          <Link href="/login" className="flex-1">
            <Button 
              className="w-full text-lg font-medium h-12 rounded-xl bg-gray-800 text-white hover:bg-gray-700"
          >
              Log In
            </Button>
          </Link>
        </div>
        
        <Button 
          variant="outline" 
          onClick={handleGoogleLogin}
          className="w-full text-lg font-medium h-12 rounded-xl border-gray-700 bg-gray-900/50 text-white hover:bg-gray-800 flex items-center justify-center gap-2"
        >
          <GoogleIcon className="w-5 h-5" />
          Log In with Google
        </Button>
      </footer>
    </div>
  );
}
