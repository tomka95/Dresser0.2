// STATUS: placeholder onboarding screen

export default function OnboardingPage() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">Welcome to Tailor</h1>
        <p className="text-gray-600 mb-8">
          Let's set up your closet and get started with AI-powered outfit
          suggestions.
        </p>
        <div className="space-y-4">
          <div className="p-4 border rounded-lg">
            <h2 className="font-semibold mb-2">Step 1: Add Your Clothes</h2>
            <p className="text-sm text-gray-600">
              Upload photos of your clothing items to build your digital closet.
            </p>
          </div>
          <div className="p-4 border rounded-lg">
            <h2 className="font-semibold mb-2">Step 2: Set Your Preferences</h2>
            <p className="text-sm text-gray-600">
              Tell us about your style preferences and occasions.
            </p>
          </div>
          <div className="p-4 border rounded-lg">
            <h2 className="font-semibold mb-2">Step 3: Get Outfit Suggestions</h2>
            <p className="text-sm text-gray-600">
              Receive AI-powered outfit recommendations tailored to you.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}






