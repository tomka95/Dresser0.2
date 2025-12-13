# Dresser Web App

Next.js frontend application for Dresser.

## Setup

1. Install dependencies (from project root):
   ```bash
   npm install
   ```

2. Run the development server:
   ```bash
   npm run dev
   # or from apps/web directory:
   cd apps/web && npm run dev
   ```

3. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Tech Stack

- **Next.js 14** (App Router)
- **React 18**
- **TypeScript**
- **Tailwind CSS**
- **shadcn/ui** (component library)
- **Zustand** (state management)
- **@dresser/contracts** (shared types and schemas)

## Project Structure

```
apps/web/
├── src/
│   ├── app/              # Next.js App Router pages
│   │   ├── (onboarding)/ # Onboarding routes
│   │   ├── closet/       # Closet page
│   │   ├── outfits/      # Outfits page
│   │   └── layout.tsx    # Root layout with navigation
│   ├── components/       # React components
│   └── lib/              # Utility functions
└── components.json       # shadcn/ui configuration
```






