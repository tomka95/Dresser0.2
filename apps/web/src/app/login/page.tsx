"use client";

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { login } from '@/lib/api/auth';
import { setAuth } from '@/lib/auth/storage';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await login({ email, password });
      console.log('Login successful:', result);
      // Store user session/token
      setAuth({
        access_token: result.access_token,
        token_type: result.token_type,
        user: result.user,
      });
      // Redirect to closet
      router.push('/closet');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-black text-white">
      {/* Header */}
      <header className="w-full p-6 flex items-center">
        <Link href="/" className="text-gray-400 hover:text-white">
          ← Back
        </Link>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex flex-col justify-center px-6">
        <div className="w-full max-w-md mx-auto">
          <h1 className="text-3xl font-bold mb-2 text-center">Welcome Back</h1>
          <p className="text-gray-400 text-center mb-8">
            Log in to your Tailor account
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email Input */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium mb-2">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full h-12 px-4 rounded-xl bg-gray-900 border border-gray-700 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="you@example.com"
              />
            </div>

            {/* Password Input */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full h-12 px-4 rounded-xl bg-gray-900 border border-gray-700 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="Your password"
              />
            </div>

            {/* Error Message */}
            {error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/50 text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Submit Button */}
            <Button
              type="submit"
              disabled={loading}
              className="w-full text-lg font-medium h-12 rounded-xl bg-white text-black hover:bg-gray-200 disabled:opacity-50"
            >
              {loading ? 'Logging in...' : 'Log In'}
            </Button>
          </form>

          {/* Signup Link */}
          <p className="text-center text-gray-400 mt-6">
            Don't have an account?{' '}
            <Link href="/signup" className="text-blue-400 hover:text-blue-300">
              Sign Up
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}

