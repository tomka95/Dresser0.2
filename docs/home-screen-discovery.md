# Home Screen Discovery & Replacement Plan

**Figma Design Reference:**
- File Key: `PjADJkZW6PJe8ucMS21ALx`
- Node ID: `26-796` (Home)

**Date:** Generated from Figma design analysis and codebase discovery

---

## A) FIGMA BREAKDOWN

### Layout Structure (Top → Bottom)

#### 1. **Status Bar** (iOS-style)
- **Location:** Top of screen
- **Content:** "9:41" (left), signal/WiFi/battery icons (right)
- **Styling:** White text/icons on dark background
- **Note:** Likely handled by browser/system, not custom implementation

#### 2. **Header/Greeting Section**
- **Location:** Directly below status bar, left-aligned
- **Components:**
  - Primary greeting: **"Hey, Tom!"** (large, bold, white text)
  - Sub-greeting: **"Wants to find your outfit for today?"** (smaller, regular weight, white text)
- **Typography:** Large bold sans-serif for main, smaller regular for sub
- **Spacing:** Significant vertical padding below status bar and between lines
- **Background:** Dark semi-transparent overlay over blurred closet image

#### 3. **Info Cards Section** (Stacked vertically, centered)
Two distinct cards with `16px` border-radius:

##### **Weather/Calendar Card**
- **Background:** Translucent light grey/white (frosted glass effect)
- **Layout:** Split vertically into two halves
- **Left Half (Weather):**
  - White outline cloud icon
  - "21" (large, bold, white) with superscript "°C" (smaller, white)
- **Right Half (Calendar):**
  - Separated by thin vertical white line
  - "10:00" (white, regular weight) above
  - "Meeting with Guy" (white, regular weight)
- **Key Components:** `CloudIcon`, `TemperatureDisplay`, `TimeEventDisplay`

##### **AI Suggestion Card**
- **Background:** Solid teal/dark green (`#1E8878` or `rgba(30, 136, 120, 1)`)
- **Layout:** Horizontal with icon on left, text on right
- **Left Icon:** Circular background (same teal) with white outline sparkle/magic wand icon
- **Right Text:**
  - "AI Suggests" (smaller, regular, white) above
  - "Layered look + boots" (larger, bold, white)
- **Key Components:** `SparkleIcon`, `AISuggestionText`

#### 4. **Clothing Item Grid Section**
- **Layout:** Two-column grid (scrollable)
- **Items Visible:** Two full items + partial view of two more
- **Item Card Structure:**
  - White rounded rectangle (`16px` border-radius)
  - Product image (clothing item photo)
  - Small grey outline heart icon in top-right corner (favorite toggle)
  - Example items shown:
    - Black jeans with brown leather tag (white background card)
    - White t-shirt on hanger (muted brown/orange background card)
- **Key Components:** `ClothingItemCard` (reusable)

#### 5. **Bottom Navigation Bar**
- **Position:** Fixed at bottom, full width, solid black background
- **Icons:** Five icons horizontally distributed (all white outline):
  - **Home** (house icon, leftmost) - Currently active
  - **Save/Bookmark** (bookmark icon)
  - **Center FAB** (Floating Action Button):
    - Large circular button
    - Teal/dark green background (`#1E8878`, matching AI Suggestion card)
    - White outline clothes hanger icon
    - Visually prominent, slightly overlaps content above
  - **Chat** (speech bubble icon)
  - **Profile** (person icon, rightmost)
- **Key Components:** `BottomNavBar`, `FloatingActionButton`

### Background & Visual Effects
- **Background Image:** Blurred image of open closet (clothes on hangers, shelves, folded items/pillows)
- **Overlay:** Dark translucent mask (`rgba(0,0,0, 0.5)` or similar) on top of background image
- **Effect:** Creates depth while maintaining foreground readability

### Typography & Spacing
- **Border Radius:** Consistent `16px` for all cards
- **Colors:**
  - Primary teal: `#1E8878` (AI card, FAB)
  - Muted brown/orange: Specific color for one item card (needs extraction)
  - White: Text and icons on dark backgrounds
  - Translucent grey: Weather/calendar card background

### Assets Needed
- **Background Image:** Blurred closet photo → Place in `public/images/closet-background-blur.jpg` (or similar)
- **Icons** (can use `lucide-react`):
  - `Cloud` (weather)
  - `Sparkles` or `Wand2` (AI suggestion)
  - `Heart` (favorite toggle on clothing items)
  - `Home` (navigation)
  - `Bookmark` (navigation)
  - `Shirt` or `Hanger` (FAB - needs specific hanger icon)
  - `MessageCircle` (chat navigation)
  - `User` (profile navigation)
- **Product Images:** Placeholder images for clothing items (initially)

---

## B) PROPOSED FILE PLAN

### Route Structure
```
src/app/
  └── page.tsx                    # Main home page (REPLACE existing)
```

### New Components Structure
```
src/components/
  ├── home/                        # NEW - Home-specific components
  │   ├── HomeHeader.tsx          # Greeting section ("Hey, Tom!", sub-greeting)
  │   ├── InfoCard.tsx            # Generic reusable card component
  │   ├── WeatherCalendarCard.tsx # Weather/Calendar card (uses InfoCard)
  │   ├── AISuggestionCard.tsx    # AI suggestion card (uses InfoCard)
  │   ├── ClothingItemCard.tsx    # Individual clothing item card (with heart icon)
  │   └── ClothingGrid.tsx        # Grid container for clothing items
  │
  └── layout/                      # NEW - Shared layout components
      └── BottomNavBar.tsx        # Bottom navigation bar with FAB
```

### Component Breakdown

#### **Reusable Components** (extracted from design):
1. **`components/home/HomeHeader.tsx`**
   - Props: `userName?: string` (defaults to "Tom" or from auth store)
   - Contains greeting text and sub-greeting
   - Handles dynamic name insertion

2. **`components/home/InfoCard.tsx`** (Generic base)
   - Props: `icon`, `primaryText`, `secondaryText?`, `backgroundColor`, `variant` ("weather" | "ai")
   - Base card component with `16px` border-radius
   - Handles translucent vs. solid backgrounds

3. **`components/home/WeatherCalendarCard.tsx`**
   - Wraps `InfoCard` with weather/calendar specific layout
   - Props: `temperature`, `unit`, `time`, `event`
   - Uses `Cloud` icon from `lucide-react`

4. **`components/home/AISuggestionCard.tsx`**
   - Wraps `InfoCard` with AI suggestion specific layout
   - Props: `suggestion`
   - Uses teal background (`#1E8878`), `Sparkles` icon
   - Links to AI suggestion functionality

5. **`components/home/ClothingItemCard.tsx`**
   - Props: `item: ClosetItem`, `onFavoriteToggle?: (itemId: string) => void`, `isFavorite?: boolean`
   - Displays item image, name (if needed), heart icon
   - Handles click navigation to `/closet/[id]`
   - Supports custom background color override

6. **`components/home/ClothingGrid.tsx`**
   - Props: `items: ClosetItem[]`, `columns?: number` (default 2)
   - Two-column grid layout
   - Scrollable container
   - Renders multiple `ClothingItemCard` instances

7. **`components/layout/BottomNavBar.tsx`**
   - Fixed position at bottom
   - Black background
   - Five navigation icons + central FAB
   - Props: `activeRoute?: string` (highlights active icon)
   - FAB uses teal color (`#1E8878`)
   - Navigation links:
     - Home → `/`
     - Bookmark → `/outfits` (or `/saved`)
     - FAB → `/closet` or modal for quick add
     - Chat → `/chat` (or placeholder)
     - Profile → `/profile` (or placeholder)

#### **Inline in `page.tsx`:**
- Main container structure
- Background image application
- Dark overlay positioning
- Overall layout orchestration (header, cards, grid, nav)
- Data fetching logic (weather, calendar, AI suggestions, closet items)

### Additional Files Needed
- **API Clients** (may need to create if missing):
  - `lib/api/weather.ts` - Weather data (mock initially)
  - `lib/api/calendar.ts` - Calendar/events data (mock initially)
  - `lib/api/ai-suggestions.ts` - AI outfit suggestions (mock initially)
  - Note: `lib/api/closet.ts` already exists (used by `useClosetStore`)

- **Stores** (may need to create):
  - `stores/useUserStore.ts` - User name/authentication state (if not exists)
  - Or extend existing auth store to include user name

---

## C) REPLACEMENT PLAN

### Current Home Route Status
- **File:** `src/app/page.tsx`
- **Current Implementation:** Simple redirect to `/sign-up`
  ```typescript
  export default function HomePage() {
    redirect('/sign-up');
  }
  ```
- **Status:** This is the ONLY home route. No `/home` or `/(app)/home` routes exist.

### Files to Replace
1. **`src/app/page.tsx`** - **REPLACE ENTIRELY**
   - Remove redirect logic
   - Implement new home screen with all components
   - Add authentication check (redirect to `/sign-up` if not authenticated)

### Redirects Needed
- **None** - Since `/` is the only home route, no redirects are required

### Link Updates Required
- **Navigation Links:**
  - Check `BottomNavBar` when implemented - ensure home icon points to `/`
  - Verify any existing navigation components don't have hardcoded links to non-existent `/home`
  - Current codebase uses `/closet`, `/outfits` - these are already correct

### Authentication Flow Considerations
- Current `page.tsx` redirects unauthenticated users to `/sign-up`
- New home screen should:
  - Check authentication status
  - If authenticated: Show full home screen
  - If not authenticated: Redirect to `/sign-up` (preserve current behavior)
- Consider: Should authenticated but onboarding-incomplete users see home, or redirect to `/(onboarding)`?

### Integration with Existing Features
- **Closet Integration:**
  - Use existing `useClosetStore` to fetch and display clothing items
  - Reuse `ClosetItem` type from `@tailor/contracts`
  - Clothing grid should display items from `useClosetStore().items`

- **Layout Considerations:**
  - Current root layout (`src/app/layout.tsx`) has:
    - Max width: `430px` (mobile-first)
    - Background: `#eeede9`
    - Scroll container structure
  - New home screen should work within this container
  - Background image/overlay will override root layout background

---

## D) RISKS / GOTCHAS

### Responsive Design
- **Risk:** Figma design is for single mobile viewport size
- **Mitigation:**
  - Test across different mobile sizes (small: 320px, large: 430px+)
  - Ensure cards don't overflow on smaller screens
  - Grid should remain two columns but handle overflow gracefully
  - Consider tablet viewports (768px+) - may need different grid layout
  - Use Tailwind responsive utilities (`sm:`, `md:`, etc.) for breakpoints

### Fixed Heights & Absolute Positioning
- **Risk:** Bottom navigation bar uses fixed positioning
- **Gotcha:** FAB overlaps content above - requires careful `z-index` management
- **Mitigation:**
  - Add bottom padding to main content area equal to nav bar height
  - Ensure scrollable content area accounts for fixed nav
  - Use `pb-20` or similar on main container to prevent content overlap
  - Test scrolling behavior with fixed nav

### Background Image & Overlay
- **Risk:** Background image may not match design exactly, overlay opacity affects readability
- **Gotcha:** Background image needs to be blurred (CSS `backdrop-blur` or pre-blurred asset)
- **Mitigation:**
  - Use CSS `filter: blur()` or `backdrop-filter` for dynamic blur
  - Or provide pre-blurred image asset
  - Ensure overlay opacity (`rgba(0,0,0, 0.5-0.7)`) provides sufficient contrast
  - Test text readability over various background images

### Missing Assets
- **Risk:** Background closet image doesn't exist
- **Action:** Source or generate blurred closet background image, place in `public/images/`
- **Risk:** Product images for clothing items may be missing
- **Mitigation:**
  - Use `ClosetItem.imageUrl` from API/store
  - Provide placeholder/fallback images
  - Handle missing images gracefully (show placeholder or default image)

### Dynamic Data Integration
- **Risk:** Weather, calendar, and AI suggestions require new API endpoints
- **Current State:** No existing API clients for these features
- **Mitigation (Mock-First Workflow):**
  - Create mock implementations in `lib/api/mock/weather.ts`, `lib/api/mock/calendar.ts`, `lib/api/mock/ai-suggestions.ts`
  - Use hardcoded data initially:
    - Weather: `{ temperature: 21, unit: '°C' }`
    - Calendar: `{ time: '10:00', event: 'Meeting with Guy' }`
    - AI Suggestion: `{ text: 'Layered look + boots' }`
  - Swap mocks for real API calls later when backend is ready
  - Document required API contract in `docs/contracts-notes.md`

### Styling Consistency
- **Risk:** Specific colors (teal `#1E8878`, muted brown) may not be in design system
- **Current State:** `tailwind.config.ts` uses HSL-based CSS variables, no custom colors defined
- **Mitigation:**
  - Add custom colors to `tailwind.config.ts`:
    ```typescript
    teal: {
      DEFAULT: '#1E8878',
      // ... shades if needed
    }
    ```
  - Or use inline styles for now, document in `docs/contracts-notes.md` for design system update
  - Ensure `16px` border-radius matches existing `--radius` token (`0.625rem` = 10px) - may need override

### Icon Availability
- **Risk:** Hanger icon for FAB may not exist in `lucide-react`
- **Current Icons Available:** `lucide-react` has `Shirt`, `ShirtIcon`, but specific "hanger" may not exist
- **Mitigation:**
  - Check `lucide-react` for closest match (`Shirt` or `Hanger` if exists)
  - If not available, create custom SVG icon in `components/icons/HangerIcon.tsx` (similar to `GoogleIcon.tsx`)

### User Name Personalization
- **Risk:** "Hey, Tom!" is hardcoded in design
- **Current State:** No user name store visible in codebase
- **Mitigation:**
  - Extract user name from auth store or user API
  - Default to "Hey!" or "Hey there!" if name unavailable
  - Check `lib/api/auth` for `getCurrentUser()` - may return user name

### Interaction States
- **Risk:** Heart icons, FAB, nav icons need hover/active/pressed states
- **Mitigation:**
  - Add `:hover`, `:active`, `[data-state]` styles using Tailwind utilities
  - Test touch interactions on mobile devices
  - Consider accessibility: keyboard navigation, focus states, ARIA labels

### Performance Considerations
- **Risk:** Multiple images (background + clothing items) may cause slow load
- **Mitigation:**
  - Lazy load clothing item images
  - Optimize background image (WebP format, appropriate size)
  - Consider image CDN for product images
  - Add loading skeletons/placeholders

### Accessibility
- **Risk:** Dark overlay may reduce contrast, affecting screen readers
- **Mitigation:**
  - Ensure sufficient contrast ratios (WCAG AA: 4.5:1 for text)
  - Add proper `alt` text for all images
  - Add ARIA labels for interactive elements (heart icons, nav items, FAB)
  - Test with screen reader
  - Ensure keyboard navigation works for all interactive elements

### State Management
- **Risk:** Weather, calendar, AI suggestions need new state management
- **Current State:** Only `useClosetStore` and `useOutfitsStore` exist
- **Mitigation:**
  - Create simple state in `page.tsx` for now (useState)
  - Or create lightweight stores if data needs to be shared across components
  - Consider caching fetched data to avoid repeated API calls

### Layout Container Constraints
- **Risk:** Root layout has `max-w-[430px]` constraint - may conflict with full-width background
- **Current Layout:** `div` with `max-w-[430px]` contains all content
- **Mitigation:**
  - Background image should be applied to outer container or body, not inside `max-w-[430px]` div
  - Consider moving background styling to root layout or using `fixed` positioning for background
  - Ensure overlay doesn't interfere with content scrolling

---

## Summary

**Key Findings:**
- Current home route (`/`) only redirects to sign-up
- No existing home screen implementation to migrate
- Design requires new components: header, info cards, clothing grid, bottom nav
- Several new API integrations needed (weather, calendar, AI) - start with mocks
- Bottom nav is shared component (should appear on other pages too)
- Authentication check needed to determine redirect vs. show home

**Recommended Approach:**
1. Create mock API clients first (weather, calendar, AI suggestions)
2. Build reusable components (`InfoCard`, `ClothingItemCard`, `BottomNavBar`)
3. Implement home page with authentication guard
4. Test responsive behavior and accessibility
5. Document any missing contracts in `docs/contracts-notes.md`

**Next Steps:**
- Begin implementation starting with component structure
- Create mock data providers for dynamic content
- Build and test incrementally
