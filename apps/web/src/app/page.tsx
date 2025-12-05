"use client";

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { FloatingClothes } from '@/components/landing/FloatingClothes';
import { GoogleIcon } from '@/components/icons/GoogleIcon';
import { startGmailOAuth } from '@/lib/api/gmail';

export default function HomePage() {
  const handleGoogleLogin = async () => {
    try {
      const { authorization_url } = await startGmailOAuth();
      // Redirect user to Google OAuth
      window.location.href = authorization_url;
    } catch (error) {
      console.error('Failed to start Google OAuth:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      alert(`Failed to connect to Google: ${errorMessage}. Please make sure the backend server is running on port 8000.`);
    }
  };
  return (
    <div className="min-h-screen flex flex-col bg-black text-white relative overflow-hidden">
      {/* Header */}
      <header className="w-full p-6 flex justify-center z-10">
        <h1 className="text-2xl font-bold tracking-widest uppercase bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-600">
          Dresser
        </h1>
      </header>

      {/* Main Visual */}
      <main className="flex-1 flex flex-col items-center justify-center relative z-0">
        <div className="w-full max-w-md">
          <FloatingClothes />
        </div>
        
        <div className="text-center px-6 mt-[-20px] z-10">
          <h2 className="text-3xl font-bold mb-2">Your Style, AI Powered</h2>
          <p className="text-gray-400">
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
          onClick={handleGoogleLogin}
          variant="outline" 
          className="w-full text-lg font-medium h-12 rounded-xl border-gray-700 bg-gray-900/50 text-white hover:bg-gray-800 flex items-center justify-center gap-2"
        >
          <GoogleIcon className="w-5 h-5" />
          Log In with Google
        </Button>
      </footer>
    </div>
  );
}
