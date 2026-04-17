# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** SOMTool
**Generated:** 2026-04-17 09:29:51
**Category:** Higher-Education / Premium Brand (Cal Lutheran)

---

## Global Rules

### Color Palette

Heritage palette: California Lutheran University Primary Purple + Primary Yellow.
Source: https://www.callutheran.edu/offices/marketing/brand/color.html

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary (brand / CTA) | `#3B2360` | `--color-primary` / `--color-cta` |
| Primary deep (hover) | `#2A1847` | `--color-primary-deep` / `--color-cta-strong` |
| Secondary (alt purple) | `#6A4C92` | `--color-secondary` |
| Highlight (accent) | `#FFC222` | `--color-highlight` |
| Highlight soft | `#FFD589` | `--color-highlight-soft` |
| Highlight wash | `#FFF5D1` | `--color-highlight-wash` |
| Highlight ink (text on yellow) | `#5B3E00` | `--highlight-ink` |
| Lavender wash (CTA soft) | `#EEE8F4` | `--color-cta-soft` |
| Background | `#FAFAF7` | `--color-background` |
| Text | `#0C0A09` | `--color-text` |

**Status palette** (Cal Lutheran secondaries):
`--s-not-contacted: #BFC5C9` · `--s-contacted: #997F39` · `--s-responded: #1E5989` · `--s-confirmed: #00854F` · `--s-declined: #E74645`

**Usage rules:**
- Primary Purple drives brand chrome, primary CTAs, section ink, and focus rings.
- Primary Yellow is reserved for accents that must draw the eye: the sidebar active indicator, registration PIN digits, feedback stars, chips, and sparingly-used "highlight" buttons. Never use yellow as body text on white (fails AA); use it on purple backgrounds or as decorative glyphs.
- Status and metric palettes remap automatically through CSS variables — templates should not hard-code status hex values.

**Color Notes:** Cal Lutheran heritage — Primary Purple `#3B2360` on warm off-white, with Primary Yellow `#FFC222` as the signature accent.

### Typography

- **Heading Font:** Fira Code
- **Body Font:** Fira Sans
- **Mood:** dashboard, data, analytics, code, technical, precise
- **Google Fonts:** [Fira Code + Fira Sans](https://fonts.google.com/share?selection.family=Fira+Code:wght@400;500;600;700|Fira+Sans:wght@300;400;500;600;700)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button — Cal Lutheran Purple */
.btn-primary {
  background: #3B2360;
  color: #FFFFFF;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  background: #2A1847;
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(59, 35, 96, 0.22);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #3B2360;
  border: 2px solid #3B2360;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

/* Highlight Button — Primary Yellow, use sparingly */
.btn-highlight {
  background: #FFC222;
  color: #5B3E00;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-highlight:hover {
  background: #FFD589;
  transform: translateY(-1px);
  box-shadow: 0 8px 22px rgba(255, 194, 34, 0.35);
}
```

### Cards

```css
.card {
  background: #FFFFFF;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

/* Accent card — top yellow stripe for subtle Cal Lu signature */
.card-accent {
  position: relative;
  background: linear-gradient(135deg, rgba(255,194,34,0.08) 0%, rgba(255,255,255,0) 55%), #FFFFFF;
  border: 1px solid rgba(255,194,34,0.28);
}
.card-accent::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, #FFC222 0%, #FFD589 100%);
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #3B2360;
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 35, 96, 0.22);
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Liquid Glass

**Keywords:** Flowing glass, morphing, smooth transitions, fluid effects, translucent, animated blur, iridescent, chromatic aberration

**Best For:** Premium SaaS, high-end e-commerce, creative platforms, branding experiences, luxury portfolios

**Key Effects:** Morphing elements (SVG/CSS), fluid animations (400-600ms curves), dynamic blur (backdrop-filter), color transitions

### Page Pattern

**Pattern Name:** Enterprise Gateway

- **Conversion Strategy:**  logo carousel,  tab switching for industries, Path selection (I am a...). Mega menu navigation. Trust signals prominent.
- **CTA Placement:** Contact Sales (Primary) + Login (Secondary)
- **Section Order:** 1. Hero (Video/Mission), 2. Solutions by Industry, 3. Solutions by Role, 4. Client Logos, 5. Contact Sales

---

## Anti-Patterns (Do NOT Use)

- ❌ Cheap visuals
- ❌ Fast animations

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
