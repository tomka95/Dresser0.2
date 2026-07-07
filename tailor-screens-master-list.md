# Tailor — Master Screen List (Claude Design Handoff)

**Goal:** redesign the entire app on the `ds/` dark-teal design system — clean, highly aesthetic, current-trend (glassmorphism, floating glass nav, soft depth, spring motion). Design every screen **and every state** below. Loading/empty/error states are first-class, not afterthoughts.

**Priority key:** `P0` = user-visible today (redesign) · `P1` = missing but implied/needed soon · `P2` = future roadmap.
**States key (design all that apply):** default · empty · loading/skeleton · error+retry · success/toast · offline · permission-denied · rate-limited/quota · not-found · incognito.

---

## 0 · GLOBAL CHROME (design once, reused everywhere)

| # | Surface | Priority | Notes |
|---|---------|----------|-------|
| G1 | **Floating glass bottom nav** | P0 | Recreate: glass/blurred, **hovering** (detached from screen edge, rounded pill, soft shadow), 4 tabs + center closet FAB. Design active/inactive/press states + FAB active state (currently never shows active). |
| G2 | AppShell (430px mobile column) | P0 | Consistent bg, safe-area, scroll behavior. |
| G3 | TopBar (back + title + action slot) | P0 | Used on every back-button screen. |
| G4 | **Global toast/snackbar host** | P1 | MISSING today. Success/error/info + undo variant. |
| G5 | **Route loading skeletons** | P1 | MISSING. Per-surface skeletons (grid, list, card, detail, chat). Apply the loading animation set. |
| G6 | **Error boundary / crash screen** | P1 | MISSING. On-brand "something broke" + retry. |
| G7 | **Offline surface** | P1 | MISSING. Banner + full-screen lost-connection. |
| G8 | Bottom Sheet + Dialog (unify) | P0 | Two modal systems today — consolidate into one visual language. |
| G9 | Empty-state template | P0 | Reusable illustration + copy + CTA pattern. |
| G10 | Loading animation library | P0 | Apply the animations already designed consistently: splash, skeleton shimmer, "Tailoring…" processing, streaming/typing, swipe-deck, image-fill. |

---

## 1 · AUTH

| # | Screen | Priority | States to design |
|---|--------|----------|------------------|
| A1 | Auth shell (bg + logo + card) | P0 | default |
| A2 | Sign In | P0 | default · loading · error · **rate-limited** · **offline** · **OAuth-error banner** (bug today) |
| A3 | Sign Up | P0 | default · loading · error · rate-limited |
| A4 | Verify-email ("check your email") | P0 | default · resend loading/sent/error |
| A5 | Forgot Password | P0 | default · loading · sent · error · rate-limited |
| A6 | Reset Password | P0 | default · loading · success · **invalid/expired-link landing** (missing) |
| A7 | Email Confirmed (celebratory) | P0 | default · loading · fetch-error |
| A8 | Google / Apple provider buttons | P0 | default · pending · error (Apple = seam) |
| A9 | Connect-Gmail modal (4 states) | P0 | disconnected · connecting · connected · error · **permission-denied (distinct)** |
| A10 | **Expired-session / re-auth interstitial** | P1 | MISSING — appears mid-session on token expiry |

---

## 2 · ONBOARDING (6-screen tap flow, own full-screen chrome)

| # | Screen | Priority | States |
|---|--------|----------|--------|
| O1 | Departments | P0 | default |
| O2 | Sizes (pickers + system switch) | P0 | default · overflow scroll |
| O3 | Fit sliders (top + bottom) | P0 | neutral-until-touched |
| O4 | Taste deck (10-swipe archetypes) | P0 | default · image-error fallback |
| O5 | Occasions (multi-select chips) | P0 | default |
| O6 | Weather + closet-seed hand-off | P0 | default · perm-denied · perm-unsupported · loading · commit-error · **offline** |
| O7 | Progress dots + Skip chrome | P0 | — |
| O8 | Completion → home | P0 | success · error-keeps-open |
| O9 | **Resume-mid-flow** design | P1 | MISSING — no resume today (refresh resets) |
| O10 | Gated-page interstitial (while status loads) | P1 | skeleton instead of blank |

---

## 3 · CLOSET

| # | Screen | Priority | States |
|---|--------|----------|--------|
| C1 | Closet grid (search + filter + FAB) | P0 | populated · empty · loading · error+retry · no-match |
| C2 | Item detail (inline field edit) | P0 | default · loading · error · save-toast |
| C3 | Item context menu (⋮) | P0 | default — **wire "Mark returned" + "Delete"** (dead today) |
| C4 | Category filter chips | P0 | selected |
| C5 | Per-field **confidence / low-confidence** review UI | P1 | Currently fake-confirmed; design a real "confirm low-confidence fields" affordance |
| C6 | **Barcode / tag scan** ingest entry | P2 | Roadmap 4th ingest source |

---

## 4 · INGESTION

| # | Screen | Priority | States |
|---|--------|----------|--------|
| I1 | AddItemDrawer (source picker) | P0 | default · unsupported/too-large/too-many |
| I2 | Add-photo page (host) | P0 | default · unauth shell |
| I3 | Photo upload surface (detect→select→commit) | P0 | pick · HEIC · detecting · committing · detect-failed · all-dup · unsupported/too-large · session-expired · commit-error+retry · **camera/photo-permission-denied** · **offline** · **quota** |
| I4 | Region/zone selector (tap/draw boxes) | P0 | populated · dup · nothing-detected · cap · occlusion/size-warn · committing |
| I5 | Swipe/review deck (Gmail + photo + chat) | P0 | populated · loading · load-error · empty (not-connected/nothing/scanning) · auto-commit · generating · commit-error+retry · **offline** · **quota** · **distinct chat source badge** |
| I6 | Generation progress pill + BackgroundTailorNotice | P0 | running · done-glow · provisional · minimized · **error (silent today)** |
| I7 | Gmail OAuth callback (headless) | P0 | — |
| I8 | **Ingest source = "chat" badge** | P1 | Today chat items masquerade as photo |

---

## 5 · STYLIST / CHAT & OUTFITS

| # | Screen | Priority | States |
|---|--------|----------|--------|
| S1 | Chat screen (SSE streaming) | P0 | populated · empty(greeting) · loading(typing) · error · offline · unauthorized · rate-limited · incognito |
| S2 | Composer (text + photo/closet attach) | P0 | default · loading · attaching · >5MB error |
| S3 | Message bubbles (user/AI/tool/error/img) | P0 | default · streaming · error · tool-label |
| S4 | History switcher sheet | P0 | populated · empty · **loading skeleton** · **load-error** (swallowed today) |
| S5 | New-chat / Delete-chat | P0 | success · error · **add delete confirm** (one-tap today) |
| S6 | Incognito toggle + banner | P0 | on · off |
| S7 | In-chat ingest card ("Review N →") | P0 | event-gated |
| S8 | Outfit collage card (server-tiled) | P0 | default · **loading skeleton** · **onError** (missing) |
| S9 | Outfit feedback (wore/swap/not-for-me) | P0 | idle · reject+chips · swap 2-step · busy · success · error |
| S10 | Outfits list / lookbook | P0 | populated · empty · loading · error — **NEEDS REAL BACKEND (mock today)** + **auth guard** |
| S11 | Outfit detail | P0 | populated · not-found · loading — real weather (hardcoded today) |
| S12 | **Outfit feedback parity on /outfits** | P1 | Feedback + collage are chat-only today |
| S13 | **Persistent tool-call + image history** | P1 | Thumbs/tool cards lost on reload |

---

## 6 · FEED / SHOPPING

| # | Screen | Priority | States |
|---|--------|----------|--------|
| F1 | Home ("feed") | P0 | populated · empty · loading-skeleton · **error** · **offline** — replace mock weather/AI cards with real |
| F2 | **Stage-1 shopping feed (GET /shop)** | P1 | MISSING frontend. Ranked wardrobe-gap feed: product cards, impression/save/dismiss, "unlocks N outfits" tag, exploration slice. Backend exists. |
| F3 | Search (closet + shop + outfits) | P0 | default · no-match · empty-notes · **loading** · **error** — shop results are mock; wire to ranker |
| F4 | Shop / product detail | P0 | default · not-found · saved-toast · **loading** · **error** · **out-of-stock** |
| F5 | **Affiliate redirect interstitial** (/out/{click_id}) | P1 | MISSING. "Taking you to {merchant}…" + click capture. Backend exists. |
| F6 | **Rate-a-look deck** (S4 surface) | P2 | Swipe deck for shopping feed candidates |
| F7 | Wishlist / saved products view | P2 | Save exists, no dedicated surface |
| F8 | **Packing lists** | P2 | Roadmap feature — trip → outfit set from closet |
| F9 | **Influencer / creator closets** | P2 | Roadmap — browse a creator's closet + shop it |

---

## 7 · PROFILE / SETTINGS

| # | Screen | Priority | States |
|---|--------|----------|--------|
| P1 | Profile (avatar + stats + Gmail + toggles) | P0 | populated · error-fallback · **loading** |
| P2 | Profile edit | P0 | default · saving · success · error |
| P3 | **My Style Profile (real)** | P1 | Today localStorage + inert. Design the REAL profile view: distilled Facts, learned preferences w/ confidence, narrative, "why this rec", edit/delete each. Transparency = trust feature. |
| P4 | Settings index | P0 | default · gmail-status · error · **loading** |
| P5 | Change password | P0 | default · validation · busy · success · error |
| P6 | Sizes & fit | P0 | default · error — wire to real store (localStorage-only today) |
| P7 | GmailConnectCard + ManageGmailSheet | P0 | all states — **wire disconnect** (dead today) |
| P8 | Logout (add confirm) | P0 | success |
| P9 | **Account deletion** | P1 | MISSING — likely GDPR/App-Store blocker. Confirm flow + cascade warning. |
| P10 | **Notifications settings** | P1 | Real toggles (daily outfit push, etc.) — local-only today |
| P11 | **Body shape / height (opt-in)** | P2 | Progressive, illustrated, inclusive; from profile screen |
| P12 | **Color-season analysis (selfie, opt-in)** | P2 | Consent-gated hook feature |
| P13 | **Budget bands / brand affinities** | P2 | Progressive profiling from feed |
| P14 | **Other connectors** | P2 | Beyond Gmail |

---

## 8 · ERRORS / SYSTEM

| # | Screen | Priority |
|---|--------|----------|
| E1 | 404 Not-Found | P0 (restyle exists) |
| E2 | Error boundary / crash | P1 (missing) |
| E3 | Offline full-screen | P1 (missing) |
| E4 | Route loading skeletons | P1 (missing) |
| E5 | Rate-limited / quota-exceeded template | P1 |
| E6 | Empty-state template | P0 |
| E7 | Permission-denied template (camera/photos/location) | P1 |

---

## 9 · DEAD / CLEANUP (do NOT redesign — flag for removal)
- `/login` (dead alias) · `/gmail-sync` (retired redirect) · `landing/FloatingClothes` (off-brand blue/purple, unused) · `OutfitImageUpload` (orphaned) · duplicate button/modal/slider systems.

---

## Design direction summary
- **System:** dark-teal `ds/` tokens. One button system, one modal system.
- **Trends to pull in:** glassmorphism, floating detached glass nav, soft layered depth/shadows, bento/asymmetric card layouts, generous spacing, spring/physics motion, tactile press feedback.
- **Motion:** apply the loading-animation set consistently across every loading/skeleton/processing/streaming state.
- **Feel:** premium, calm, editorial — "intelligent post-purchase wardrobe utility," not a busy marketplace.
- **States are the job:** every screen ships with empty/loading/error designed, not just the happy path.
