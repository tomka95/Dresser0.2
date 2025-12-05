import Link from 'next/link';

export default function HomePage() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="max-w-2xl mx-auto text-center">
        <h1 className="text-4xl font-bold mb-4">Welcome to Dresser</h1>
        <p className="text-lg text-gray-600 mb-8">
          Your AI-powered closet and outfit stylist
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/onboarding"
            className="px-6 py-3 bg-black text-white rounded-lg hover:bg-gray-800"
          >
            Get Started
          </Link>
          <Link
            href="/closet"
            className="px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            View Closet
          </Link>
        </div>
      </div>
    </div>
  );
}



