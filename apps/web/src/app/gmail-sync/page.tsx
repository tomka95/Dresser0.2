"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, useSpring, useTransform } from "framer-motion";
import { extractClothingFromGmail } from "@/lib/api/gmail";
import { getCurrentUser } from "@/lib/api/auth";
import { Button } from "@/components/ui/button";

export default function GmailSyncPage() {
  const router = useRouter();
  const [isExtracting, setIsExtracting] = useState(true);
  const [itemsFound, setItemsFound] = useState(0);
  const [finalCount, setFinalCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);

  // Animated counter using Framer Motion
  const spring = useSpring(0, { stiffness: 50, damping: 30 });
  const display = useTransform(spring, (current) =>
    Math.round(current)
  );

  useEffect(() => {
    // Start extraction immediately on mount
    const startExtraction = async () => {
      try {
        // First, check if sync already completed
        const userInfo = await getCurrentUser();
        if (userInfo.gmail_sync_completed_at) {
          // Already synced, redirect to closet
          router.push("/closet");
          return;
        }

        // Not synced, proceed with extraction
        setIsExtracting(true);
        setError(null);
        setItemsFound(0);
        setFinalCount(0);
        setIsComplete(false);

        // Call the extraction endpoint
        const result = await extractClothingFromGmail();

        // Set final count
        const count = result.items.length;
        setFinalCount(count);

        // Animate counter from 0 to final count
        spring.set(count);

        // Wait for animation to complete, then mark as complete
        setTimeout(() => {
          setIsComplete(true);
          setIsExtracting(false);

          // Wait 1-2 seconds showing final count, then redirect
          setTimeout(() => {
            router.push("/closet");
          }, 2000);
        }, 2000);
      } catch (e: any) {
        console.error("Gmail extraction error:", e);
        setError(e.message || "Failed to extract clothing items from Gmail");
        setIsExtracting(false);
        spring.set(0);
      }
    };

    startExtraction();
  }, [router, spring]);

  const handleRetry = () => {
    setError(null);
    // Trigger re-extraction by resetting state
    setIsExtracting(true);
    setItemsFound(0);
    setFinalCount(0);
    setIsComplete(false);

    // Restart extraction
    const startExtraction = async () => {
      try {
        const result = await extractClothingFromGmail();
        const count = result.items.length;
        setFinalCount(count);
        spring.set(count);

        setTimeout(() => {
          setIsComplete(true);
          setIsExtracting(false);
          setTimeout(() => {
            router.push("/closet");
          }, 2000);
        }, 2000);
      } catch (e: any) {
        setError(e.message || "Failed to extract clothing items from Gmail");
        setIsExtracting(false);
        spring.set(0);
      }
    };

    startExtraction();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-black text-white relative overflow-hidden">
      {/* Background Glow */}
      <div className="absolute inset-0 bg-gradient-to-b from-blue-500/10 to-purple-500/10 blur-3xl" />

      <div className="relative z-10 text-center px-6 max-w-md">
        {error ? (
          // Error State
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            <h1 className="text-2xl font-bold mb-4 text-red-400">
              Extraction Failed
            </h1>
            <p className="text-gray-400 mb-6">{error}</p>
            <Button
              onClick={handleRetry}
              className="px-6 py-3 bg-white text-black rounded-xl hover:bg-gray-200 transition-colors"
            >
              Try Again
            </Button>
            <div className="mt-4">
              <button
                onClick={() => router.push("/closet")}
                className="text-sm text-gray-500 hover:text-gray-300 underline"
              >
                Skip and go to closet
              </button>
            </div>
          </motion.div>
        ) : (
          // Loading/Complete State
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            {/* Spinner */}
            {isExtracting && (
              <motion.div
                animate={{ rotate: 360 }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                  ease: "linear",
                }}
                className="mx-auto w-16 h-16 border-4 border-white/20 border-t-white rounded-full"
              />
            )}

            {/* Large Animated Counter */}
            <div className="space-y-2">
              <motion.div
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 200, damping: 15 }}
                className="text-8xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-600"
              >
                <motion.span>{display}</motion.span>
              </motion.div>

              {/* Status Text */}
              <motion.p
                key={isComplete ? "complete" : "scanning"}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xl text-gray-300"
              >
                {isComplete
                  ? "Items found!"
                  : isExtracting
                  ? "Scanning your Gmail..."
                  : "Processing..."}
              </motion.p>

              {isComplete && (
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.3 }}
                  className="text-sm text-gray-500"
                >
                  Redirecting to your closet...
                </motion.p>
              )}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}

