# SOM Event OS — Design System v2

Neutral-first, multi-tenant. The product's core surfaces are identical across every school; each tenant's brand lives in `static/brand/<slug>/brand.css` and overrides ONLY the `--brand-*` tokens. Cal Lutheran is the first tenant — not the product's skin.

Reference baseline: Linear + Vercel + Stripe Dashboard. Typography: **Geist** (body/UI) + **Geist Mono** (code/IDs/PINs) + **Instrument Serif** (display only).

---

## 1. Palette

### 1.1 Neutral core (tenant-agnostic — never overridden)

| Token               | Hex        | Use                                              |
| ------------------- | ---------- | ------------------------------------------------ |
| `--surface`         | `#FAFAF7`  | App background (warm off-white)                  |
| `--surface-raised`  | `#FFFFFF`  | Cards, panels, inputs                            |
| `--surface-sunken`  | `#F4F4EF`  | Hover rows, code blocks, tinted fills            |
| `--surface-tinted`  | `#F6F5F1`  | Table headers, modal footers                     |
| `--surface-dark`    | `#0F1115`  | Event-day mission control band                   |
| `--border`          | `#E6E4DD`  | Default borders                                  |
| `--border-strong`   | `#CFCCC2`  | Input border on hover                            |
| `--border-subtle`   | `#EFEDE6`  | Table row separators                             |
| `--text`            | `#111318`  | Body text                                        |
| `--text-strong`     | `#0B0D11`  | Headlines                                        |
| `--text-muted`      | `#5B616B`  | Secondary text                                   |
| `--text-subtle`     | `#8A8F98`  | Tertiary text, subtle metadata                   |
| `--text-inverse`    | `#FAFAF9`  | Text on dark surfaces                            |

### 1.2 Semantic (tenant-agnostic — used for status, validation, alerts)

| Token          | Hex        | Use              |
| -------------- | ---------- | ---------------- |
| `--success`    | `#1A7F4B`  | Success state    |
| `--warning`    | `#C77A0B`  | Warning state    |
| `--danger`     | `#C9342D`  | Destructive      |
| `--info`       | `#1E5989`  | Informational    |

Each has `-fg`, `-soft`, and `-ink` companion tokens for background / contrast.

### 1.3 Chart palette (tenant-agnostic, categorical)

Linear/Vercel-style balanced categorical set. Same colors across every tenant so analytics screenshots are comparable between schools.

| Token       | Hex        | Role    |
| ----------- | ---------- | ------- |
| `--chart-1` | `#1E5989`  | blue    |
| `--chart-2` | `#C77A0B`  | amber   |
| `--chart-3` | `#1A7F4B`  | green   |
| `--chart-4` | `#6A4C92`  | violet  |
| `--chart-5` | `#2F8F8F`  | teal    |
| `--chart-6` | `#C9342D`  | red     |
| `--chart-7` | `#B04A6F`  | pink    |
| `--chart-8` | `#4E5766`  | slate   |

### 1.4 Brand layer (tenant-overridable)

Each tenant's `brand.css` may declare ONLY these six tokens. Nothing else.

| Token                   | Default (generic slate) | Purpose                                           |
| ----------------------- | ----------------------- | ------------------------------------------------- |
| `--brand-primary`       | `#3E4B63`               | School accent color                               |
| `--brand-primary-hover` | `#2D3849`               | Darker step for hover                             |
| `--brand-primary-fg`    | `#FFFFFF`               | Text-on-brand (must hit 4.5:1)                    |
| `--brand-soft`          | `#ECEEF3`               | Hover rail / active-nav background (~10% tint)    |
| `--brand-ring`          | `rgba(62,75,99,.30)`    | Focus ring                                        |
| `--brand-accent`        | `#3E4B63`               | Optional secondary (most tenants leave = primary) |

**Brand surface contract** — the six places `--brand-*` is *allowed*:

1. Sidebar header logo lockup.
2. Sidebar active-nav 3px left indicator.
3. The single primary CTA per view (`.btn-primary`).
4. Active tab underline (`.tab[aria-selected="true"]::after`).
5. Focus ring (`:focus-visible`).
6. Login / PIN gate small logo + primary button.

**Forbidden**: card/row/page/hero backgrounds, chart categorical colors, semantic states, table row hovers, empty-state illustrations.

### 1.5 Shipped tenants

- **`callutheran`** — Cal Lutheran SOM. Hint-purple (desaturated from the brand purple so it reads as a small accent, not dominance). `--brand-accent` keeps a muted warm yellow for the optional chip.
- **`default`** — neutral slate-blue. Used for any school we haven't built a brand kit for.

Onboarding a new tenant = drop a `static/brand/<slug>/` folder with `logo.svg`, `mark.svg`, `brand.css`, then set `branding.json` → `{"slug": "<slug>", ...}`.

---

## 2. Typography

- **Body/UI**: Geist (400/500/600/700)
- **Mono** (code, IDs, PINs, table numerics): Geist Mono (400/500/600)
- **Display** (only for hero H1 with `.display`): Instrument Serif, italic variant for expressive moments

### Type scale (8pt-ish)

| Token           | Size     | Line height | Use                                |
| --------------- | -------- | ----------- | ---------------------------------- |
| `--fs-display`  | 2.5rem   | 1.08        | Hero display (Instrument Serif)    |
| `--fs-h1`       | 2rem     | 1.25        | Page H1                            |
| `--fs-h2`       | 1.5rem   | 1.25        | Section H2                         |
| `--fs-h3`       | 1.125rem | 1.25        | Card / sub-section heading         |
| `--fs-body`     | 0.94rem  | 1.55        | Body                               |
| `--fs-sm`       | 0.85rem  | 1.55        | UI chrome                          |
| `--fs-xs`       | 0.78rem  | 1.55        | Chips, captions                    |
| `--fs-mono-sm`  | 0.78rem  | 1.55        | Eyebrows, KPI labels, timestamps   |

### Tracking

- Body: `-0.005em`
- H1/H2/H3: `-0.02em`
- Display (Instrument Serif): `-0.03em`

---

## 3. Spacing (8pt grid)

| Token            | Value                        |
| ---------------- | ---------------------------- |
| `--space-2xs`    | 2px                          |
| `--space-xs`     | 4px                          |
| `--space-sm`     | 8px                          |
| `--space-md`     | 16px                         |
| `--space-lg`     | 24px                         |
| `--space-xl`     | 32px                         |
| `--space-2xl`    | 48px                         |
| `--space-3xl`    | 64px                         |
| `--space-page-x` | `clamp(1rem, 3vw, 2.25rem)`  |

Content area max-width: 1240px (wide variant: 1440px).

---

## 4. Radius

`--radius-xs: 6px` · `--radius-sm: 8px` · `--radius: 10px` · `--radius-lg: 14px` · `--radius-xl: 20px` · `--radius-pill: 999px`.

---

## 5. Elevation (5 tiers)

| Token            | Use                                         |
| ---------------- | ------------------------------------------- |
| `--elev-rest`    | Cards at rest                               |
| `--elev-hover`   | Cards on hover, bulk-bar pill               |
| `--elev-float`   | Popovers, menus, drawers                    |
| `--elev-modal`   | Modals                                      |
| `--elev-overlay` | Full-screen overlays, command palette       |

---

## 6. Motion

- `--dur-fast`: 120ms (hover, color swap)
- `--dur`: 180ms (toasts, panel slide)
- `--dur-slow`: 280ms (command palette, drawer)
- `--ease-out`, `--ease-in-out`, `--ease-spring` (reserved for one-off delight on primary CTAs)
- `--motion-fast-in`, `--motion-out` preset composites
- All animation respects `prefers-reduced-motion: reduce`.

---

## 7. Components

Canonical primitives (CSS classes in `static/css/som-theme.css`):

- `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-subtle`, `.btn-success`, `.btn-danger`, sizes `.btn-sm` / `.btn-lg` / `.btn-hero`
- `.tabs` + `.tab` (with `.tab-count` pill; `role="tablist"` ready)
- `.segmented-control` (view/density switches)
- `.table-toolbar` (search input, filter chips, sort)
- `.filter-chip`, `.bulk-bar`
- `.alert` + `.alert-info` / `.alert-success` / `.alert-warning` / `.alert-danger`
- `.toast` + `.toast-stack` (bottom-right, animated in/out)
- `.empty-state-card` (icon + title + copy + CTA)
- `.skeleton` (`.skeleton-text`, `-title`, `-avatar`, `-row`, `-card`)
- `.stat-tile` (label, value, delta, sub)
- `.progress-ring`, `.progress-bar`
- `.kv-list` (two-column definition list)
- `.sticky-actions` (sticky save bar)
- `.popover`, `.popover-item`, `.popover-divider`
- `.cmdk-overlay` + `.cmdk-panel` (command palette, `Cmd/Ctrl+K`)
- `.modal-overlay` + `.modal-panel`
- `.drawer-overlay` + `.drawer-panel`
- `.stepper` (outreach funnel, event create)
- `.mc-band` (mission-control dark surface band)
- `.pin-keypad`, `.pin-form`, `.pin-input`

---

## 8. Accessibility acceptance gate

Every touched template ships through this checklist:

- [ ] No emoji as UI icon (SVG from Lucide/Heroicons only)
- [ ] Every interactive element has `cursor: pointer` and a visible focus ring
- [ ] Hover states never use layout-shifting transforms — only color/opacity/shadow
- [ ] All form inputs have visible labels; all images have `alt`; all buttons have accessible names
- [ ] Text contrast ≥ 4.5:1 on both `--surface` and `--surface-dark`, tested with both shipped tenants
- [ ] `--brand-*` appears only in the six contracted surfaces
- [ ] No horizontal scroll at 375px; visual QA at 375 / 768 / 1024 / 1440
- [ ] `prefers-reduced-motion: reduce` collapses all non-essential motion

---

## 9. Reference model per surface

Every redesign task copies a named best-in-class product pattern.

| Surface               | Reference                                                      |
| --------------------- | -------------------------------------------------------------- |
| Home dashboard        | Stripe Dashboard home + Linear Inbox + Vercel overview         |
| Event hub tabs        | GitHub repo tabs + Linear project tabs                         |
| Guests table          | Linear issue list + Attio CRM + Airtable                       |
| Outreach funnel       | Mailchimp / Resend campaign builder + Intercom outbound        |
| Schedule / calendar   | Cal.com month view + Linear cycles                             |
| Analytics             | Stripe Sigma + Vercel Analytics + PostHog                      |
| Registration desk     | Square POS two-pane + Eventbrite Organizer                     |
| PIN gate              | iOS lockscreen keypad + 1Password desktop unlock               |
| Command palette       | Linear / Raycast / GitHub Cmd+K                                |
| Settings              | Stripe settings + Vercel project settings                      |
| Empty states          | Linear / Height / Superhuman                                   |
| Sidebar               | Linear workspace + Vercel sidebar                              |
| Flash / toast         | Linear toast stack + Stripe banners                            |
| Tenant branding       | Linear workspace color + Notion workspace icon + Vercel team   |
