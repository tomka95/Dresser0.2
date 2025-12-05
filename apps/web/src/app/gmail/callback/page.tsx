"use client";

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { handleGmailCallback, extractClothingFromGmail } from '@/lib/api/gmail';

export default function GmailCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState('Processing...');

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (code && state) {
      handleCallback(code, state);
    } else {
      setStatus('Error: Missing authorization code');
    }
  }, [searchParams]);

  const handleCallback = async (code: string, state: string) => {
    try {
      setStatus('Exchanging authorization code...');
      const credentials = await handleGmailCallback(code, state);
      
      // Store credentials (you might want to use a state management solution)
      localStorage.setItem('gmail_credentials', JSON.stringify(credentials));
      
      setStatus('Scanning your emails for clothing items...');
      const items = await extractClothingFromGmail(credentials);
      
      setStatus('Success! Redirecting...');
      // Redirect to closet or items page
      setTimeout(() => router.push('/closet'), 1500);
    } catch (error) {
      setStatus(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-black text-white">
      <div className="text-center">
        <h1 className="text-2xl font-bold mb-4">Connecting to Gmail</h1>
        <p className="text-gray-400">{status}</p>
      </div>
    </div>
  );
}

