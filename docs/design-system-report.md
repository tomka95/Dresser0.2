# Tailor Design System - Implementation Report

**Source:** Figma Design System (File: `PjADJkZW6PJe8ucMS21ALx`)  
**Target Stack:** Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui  
**Generated:** Based on Figma MCP extraction

---

## 1. Design Tokens

### 1.1 Colors (Light Theme)

#### Semantic Color Palette

| Token Name | Hex Value | Usage | CSS Variable Mapping |
|------------|-----------|-------|---------------------|
| **Primary** | `#084B4D` | Primary actions, selected states, CTAs | `--primary` |
| **Secondary** | `#EEEDEA` | Secondary backgrounds, subtle elements | `--secondary` |
| **White** | `#F4F4F4` | Backgrounds, cards | `--white` or `--background` |
| **Black** | `#1F2020` | Primary text, headings | `--black` or `--foreground` |
| **Gray 1** | `#424343` | Secondary text, borders | `--gray-1` |
| **Gray 2** | `#A1A1A1` | Tertiary text, disabled states | `--gray-2` |
| **Grey** | `#BABABA` | Placeholder text, input borders | `--grey` or `--input` |
| **Grey Dark 1** | `#7F7F7F` | Muted text, unselected badges | `--grey-dark-1` or `--muted-foreground` |
| **Default/Black** | `#000000` | Pure black for icons, emphasis | `--default` |

#### Color Mapping Strategy

**Current State:** The project uses HSL-based CSS variables in `globals.css` (shadcn/ui pattern).

**Recommended Implementation:**
1. **Keep HSL format** for theme switching capability
2. **Map Figma hex values to HSL** and update CSS variables
3. **Maintain semantic naming** aligned with shadcn/ui conventions

**Proposed CSS Variable Updates:**

```css
:root {
  /* Primary Palette */
  --primary: 180 85% 16%;           /* #084B4D */
  --primary-foreground: 0 0% 100%;  /* White text on primary */
  
  /* Secondary Palette */
  --secondary: 40 10% 93%;           /* #EEEDEA */
  --secondary-foreground: 0 0% 12%;  /* #1F2020 */
  
  /* Backgrounds */
  --background: 0 0% 96%;            /* #F4F4F4 */
  --foreground: 0 0% 12%;            /* #1F2020 */
  
  /* Grays */
  --gray-1: 0 0% 26%;                /* #424343 */
  --gray-2: 0 0% 63%;                /* #A1A1A1 */
  --grey: 0 0% 73%;                  /* #BABABA */
  --grey-dark-1: 0 0% 50%;           /* #7F7F7F */
  
  /* Semantic Mappings */
  --muted: 0 0% 96%;                 /* #F4F4F4 */
  --muted-foreground: 0 0% 50%;       /* #7F7F7F */
  --border: 0 0% 73%;                /* #BABABA */
  --input: 0 0% 73%;                 /* #BABABA */
  --ring: 180 85% 16%;               /* Primary for focus rings */
}
```

**⚠️ Note:** No raw hex values should appear in component code. Always use CSS variables or Tailwind semantic classes.

---

### 1.2 Typography

#### Font Families

| Font Family | Usage | Weights Available |
|-------------|-------|------------------|
| **Inter** | Primary UI font (body, buttons, inputs) | Regular (400), Medium (500), Bold (700) |
| **DM Sans** | Headings, emphasis | Regular (400), Bold (700) |

#### Type Scale

| Token Name | Font Family | Size | Weight | Line Height | Letter Spacing | Usage |
|------------|-------------|------|--------|-------------|----------------|-------|
| `text-3xl/bold` | Inter | 36px | 700 | 46px | 0 | Modal titles, major headings |
| `text-ms/regular` | Inter | 16px | 400 | 22px | 0 | Body text, button labels |
| `text-s/regular` | Inter | 14px | 400 | 18px | 0 | Small text, placeholders |
| `text-sm/medium` | Inter | 14px | 500 | 18px | 0 | Badge text, labels |
| `text-ms/regular` (DM Sans) | DM Sans | 16px | 400 | 20px | 0.2px | Section labels, category headers |

**Typography Implementation:**

```css
/* Add to globals.css or create typography.css */
@layer base {
  body {
    font-family: 'Inter', sans-serif;
  }
  
  h1, h2, h3, h4, h5, h6 {
    font-family: 'DM Sans', sans-serif;
  }
}
```

**Tailwind Config Extension:**

```typescript
// tailwind.config.ts
theme: {
  extend: {
    fontFamily: {
      sans: ['Inter', 'sans-serif'],
      heading: ['DM Sans', 'sans-serif'],
    },
    fontSize: {
      '3xl': ['36px', { lineHeight: '46px', fontWeight: '700' }],
      'ms': ['16px', { lineHeight: '22px', fontWeight: '400' }],
      's': ['14px', { lineHeight: '18px', fontWeight: '400' }],
      'sm': ['14px', { lineHeight: '18px', fontWeight: '500' }],
    },
  },
}
```

---

### 1.3 Spacing Scale

**Observed Spacing Values:**

| Value | Usage | Tailwind Class |
|-------|-------|---------------|
| 10px | Small gaps, button padding | `gap-2.5` or `p-2.5` |
| 11px | Chip/badge spacing | `gap-[11px]` |
| 12px | Medium gaps | `gap-3` |
| 15px | Input padding, badge padding | `px-[15px]` or `p-[15px]` |
| 17px | Larger gaps | `gap-[17px]` |
| 20px | Button vertical padding | `py-5` |
| 24px | Modal padding | `p-6` |
| 35px | Large section gaps | `gap-[35px]` |

**Recommended Standardization:**

Use Tailwind's default spacing scale where possible, with custom values for specific design requirements:

```typescript
// tailwind.config.ts
theme: {
  extend: {
    spacing: {
      '2.5': '10px',
      '4.5': '11px',
      '4.25': '17px',
      '3.75': '15px',
      '8.75': '35px',
    },
  },
}
```

---

### 1.4 Border Radius

| Value | Usage | Tailwind Class |
|-------|-------|---------------|
| 10px | Buttons, inputs, cards | `rounded-[10px]` or `rounded-lg` (custom) |
| 30px | Badges, pills, modal top corners | `rounded-[30px]` or `rounded-full` (if 30px ≈ full) |

**Implementation:**

```typescript
// tailwind.config.ts
theme: {
  extend: {
    borderRadius: {
      'button': '10px',
      'badge': '30px',
      'modal-top': '30px',
    },
  },
}
```

---

### 1.5 Shadows

**Status:** No explicit shadow tokens observed in extracted components.  
**Recommendation:** Define shadow tokens based on shadcn/ui defaults or add custom shadows if needed in design.

---

### 1.6 Grid & Breakpoints

**Status:** Grid system not explicitly extracted from Figma.  
**Current:** Tailwind default breakpoints (sm, md, lg, xl, 2xl).  
**Recommendation:** Verify with design team if custom breakpoints are required.

**Observed Layout Patterns:**
- Mobile-first design (375px width references)
- Responsive grid: `grid-cols-2 md:grid-cols-3 lg:grid-cols-4` (from existing closet page)

---

## 2. Component Inventory

### 2.1 Button Component

**Variants Observed:**
- **Primary:** Dark teal background (`#084B4D`), white text
- **Secondary/Outline:** White background, gray border (`#7F7F7F`), black text
- **With Icon:** Right-aligned chevron icon

**Props Needed:**
```typescript
interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'outline';
  size?: 'default' | 'sm' | 'lg';
  icon?: 'left' | 'right' | 'none';
  disabled?: boolean;
  loading?: boolean;
}
```

**States:**
- Default
- Hover (darker primary: `primary/90`)
- Active
- Disabled (`opacity-50`, `pointer-events-none`)
- Loading (spinner + disabled state)

**Current Implementation:** `components/ui/button.tsx` exists but uses shadcn/ui defaults.  
**Action Required:** Update to match Figma design tokens.

---

### 2.2 Input Text Component

**Variants Observed:**
- **Icon Left:** Search icon on left
- **Icon Right:** Icon on right
- **No Icon:** Plain input

**States:**
- Default (gray border `#BABABA`, placeholder `#BABABA`)
- Active/Focused (black border, black text)
- Disabled

**Props Needed:**
```typescript
interface InputTextProps {
  icon?: 'left' | 'right' | 'none';
  placeholder?: string;
  value?: string;
  disabled?: boolean;
  error?: boolean;
}
```

**Styling:**
- Height: `45px`
- Border: `1px solid #BABABA`
- Border radius: `10px`
- Padding: `15px`
- Font: Inter Regular 14px

**Action Required:** Create or update input component to match design.

---

### 2.3 Badge Component

**Variants:**
- **Primary/Selected:** Dark teal background (`#084B4D`), white text
- **Default/Unselected:** No background, gray text (`#7F7F7F`)

**Props Needed:**
```typescript
interface BadgeProps {
  variant?: 'primary' | 'default';
  selected?: boolean;
  children: React.ReactNode;
}
```

**Styling:**
- Height: `25px`
- Padding: `15px` horizontal, `10px` vertical
- Border radius: `30px` (pill shape)
- Font: Inter Medium 14px

**Action Required:** Create badge component or extend existing.

---

### 2.4 Filter Modal Component

**Structure:**
- Header: Title + close icon
- Sections: Category, Sort By, Price Range
- Footer: Apply Filter button

**Props Needed:**
```typescript
interface FilterModalProps {
  isOpen: boolean;
  onClose: () => void;
  onApply: (filters: FilterState) => void;
  categories?: string[];
  sortOptions?: string[];
}
```

**Styling:**
- Background: White
- Border radius: `30px` top corners
- Padding: `24px`
- Gap between sections: `35px`
- Gap within sections: `10px`

**Action Required:** Create filter modal component.

---

### 2.5 ProgressBar Component

**Status:** Not found in extracted components.  
**Action Required:** Request node ID or design reference from design team.

---

### 2.6 Navigation Component

**Status:** Not found in extracted components.  
**Observed:** Tab bar with active/inactive states referenced in metadata.  
**Action Required:** Request specific node IDs for Nav components.

---

### 2.7 Auth Components (Login/Signup)

**Status:** Not found in extracted components.  
**Current:** Basic auth pages exist in `app/login` and `app/signup`.  
**Action Required:** Request design references or node IDs.

---

### 2.8 Home Page Components

**Status:** Not found in extracted components.  
**Action Required:** Request design references.

---

### 2.9 Profile Page Components

**Status:** Not found in extracted components.  
**Action Required:** Request design references.

---

### 2.10 Closet Page Components

**Status:** Partially implemented.  
**Current:** Closet grid exists (`app/closet/page.tsx`).  
**Action Required:** Verify design alignment with Figma specs.

---

## 3. Design Inconsistencies & Notes

### 3.1 Color Naming
- **Inconsistency:** Figma uses both "Gray" and "Grey" spellings
  - `Gray 1`, `Gray 2` vs `Grey`, `Grey Dark 1`
- **Recommendation:** Standardize to one spelling (suggest "Gray" for consistency with Tailwind)

### 3.2 Typography
- **Inconsistency:** Two font families (Inter and DM Sans) used for similar purposes
- **Recommendation:** Clarify usage guidelines:
  - Inter: UI elements, body text, buttons
  - DM Sans: Headings, section labels

### 3.3 Spacing
- **Observation:** Non-standard spacing values (11px, 17px, 35px)
- **Recommendation:** Document when to use custom vs. standard Tailwind spacing

### 3.4 Component States
- **Missing:** Hover, active, focus states not fully extracted
- **Action Required:** Request state variants from design team or infer from design system patterns

---

## 4. Implementation Roadmap

### Phase 1: Design Tokens (Priority: High)
1. ✅ Extract color palette
2. ⏳ Convert hex to HSL and update `globals.css`
3. ⏳ Update `tailwind.config.ts` with custom spacing, radius, typography
4. ⏳ Add font imports (Inter, DM Sans) to layout

### Phase 2: Base Components (Priority: High)
1. ⏳ Update Button component with Figma variants
2. ⏳ Create/update Input component
3. ⏳ Create Badge component
4. ⏳ Verify shadcn/ui components align with design

### Phase 3: Complex Components (Priority: Medium)
1. ⏳ Create Filter Modal component
2. ⏳ Request and implement ProgressBar
3. ⏳ Request and implement Navigation components
4. ⏳ Update Auth pages to match design

### Phase 4: Page-Level Implementation (Priority: Medium)
1. ⏳ Update Home page
2. ⏳ Update Profile page
3. ⏳ Verify Closet page alignment

### Phase 5: Polish & Documentation (Priority: Low)
1. ⏳ Document component usage patterns
2. ⏳ Create Storybook or component showcase
3. ⏳ Verify accessibility (contrast ratios, focus states)

---

## 5. CSS Variable Mapping Plan

### Current State
- Uses HSL-based variables (shadcn/ui pattern)
- Variables defined in `globals.css`

### Proposed Updates

**File: `apps/web/src/app/globals.css`**

```css
@layer base {
  :root {
    /* Primary Palette - Converted from #084B4D */
    --primary: 180 85% 16%;
    --primary-foreground: 0 0% 100%;
    
    /* Secondary Palette - Converted from #EEEDEA */
    --secondary: 40 10% 93%;
    --secondary-foreground: 0 0% 12%;
    
    /* Backgrounds - Converted from #F4F4F4 */
    --background: 0 0% 96%;
    --foreground: 0 0% 12%; /* #1F2020 */
    
    /* Grays - Converted from Figma values */
    --gray-1: 0 0% 26%;      /* #424343 */
    --gray-2: 0 0% 63%;      /* #A1A1A1 */
    --grey: 0 0% 73%;        /* #BABABA */
    --grey-dark-1: 0 0% 50%; /* #7F7F7F */
    
    /* Semantic Mappings */
    --muted: 0 0% 96%;
    --muted-foreground: 0 0% 50%;
    --border: 0 0% 73%;
    --input: 0 0% 73%;
    --ring: 180 85% 16%;
    
    /* Border Radius */
    --radius: 0.625rem; /* 10px */
    --radius-badge: 1.875rem; /* 30px */
  }
}
```

**File: `apps/web/tailwind.config.ts`**

```typescript
theme: {
  extend: {
    colors: {
      // Keep existing shadcn/ui mappings
      border: 'hsl(var(--border))',
      input: 'hsl(var(--input))',
      // ... existing colors ...
      
      // Add Figma-specific grays if needed
      'gray-figma-1': 'hsl(var(--gray-1))',
      'gray-figma-2': 'hsl(var(--gray-2))',
    },
    borderRadius: {
      'button': '10px',
      'badge': '30px',
    },
    fontFamily: {
      sans: ['Inter', 'sans-serif'],
      heading: ['DM Sans', 'sans-serif'],
    },
    spacing: {
      '2.5': '10px',
      '4.5': '11px',
      '4.25': '17px',
      '3.75': '15px',
      '8.75': '35px',
    },
  },
}
```

---

## 6. Component Props & States Summary

### Button
- **Variants:** primary, secondary, outline
- **Sizes:** default (50px), sm, lg
- **States:** default, hover, active, disabled, loading
- **Icons:** left, right, none

### Input
- **Variants:** icon-left, icon-right, no-icon
- **States:** default, focused, disabled, error
- **Styling:** 45px height, 10px radius, 15px padding

### Badge
- **Variants:** primary (selected), default (unselected)
- **States:** selected, unselected
- **Styling:** 25px height, 30px radius (pill), 15px horizontal padding

### Filter Modal
- **Sections:** Category, Sort By, Price Range
- **Actions:** Apply, Close
- **Styling:** 30px top radius, 24px padding, 35px section gaps

---

## 7. Next Steps

1. **Review this report** with design team for accuracy
2. **Request missing components:** ProgressBar, Nav, Auth, Home, Profile node IDs
3. **Request Typography page** node ID for complete type scale
4. **Request Grid/Icons pages** if they exist
5. **Begin Phase 1 implementation:** Update design tokens in codebase
6. **Create component library:** Implement base components matching Figma specs

---

## 8. Visual References

Screenshots captured for:
- ✅ Colors page (Light Theme)
- ✅ Components page (Buttons, Inputs, Badges, Filter)
- ✅ Button Primary variant
- ✅ Input Text with icon

**Note:** Screenshots are stored temporarily (7 days) via Figma MCP. For permanent reference, download and store in `docs/design-system-screenshots/`.

---

**Report Generated:** Based on Figma MCP extraction  
**Figma File:** `PjADJkZW6PJe8ucMS21ALx`  
**Last Updated:** [Current Date]
