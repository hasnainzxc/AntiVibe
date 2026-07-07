---
displayName: AntiVibe Security Dashboard
theme:
  colorMode: DARK
  colorVariant: TONAL_SPOT
  customColor: "#6366F1"
  headlineFont: INTER
  bodyFont: INTER
  labelFont: INTER
  roundness: ROUND_EIGHT
  typography:
    display-lg:
      fontFamily: Inter
      fontSize: 36px
      fontWeight: "700"
      lineHeight: 1.1
      letterSpacing: 0px
    heading-1:
      fontFamily: Inter
      fontSize: 36px
      fontWeight: "700"
      lineHeight: 1.1
      letterSpacing: 0px
    heading-2:
      fontFamily: Inter
      fontSize: 24px
      fontWeight: "600"
      lineHeight: 1.2
      letterSpacing: 0px
    heading-3:
      fontFamily: Inter
      fontSize: 18px
      fontWeight: "600"
      lineHeight: 1.3
      letterSpacing: 0px
    body-md:
      fontFamily: Inter
      fontSize: 15px
      fontWeight: "400"
      lineHeight: 1.6
      letterSpacing: 0px
    body-sm:
      fontFamily: Inter
      fontSize: 13px
      fontWeight: "400"
      lineHeight: 1.5
      letterSpacing: 0px
    label:
      fontFamily: Inter
      fontSize: 12px
      fontWeight: "500"
      lineHeight: 1.5
      letterSpacing: 0.05em
    mono:
      fontFamily: JetBrains Mono
      fontSize: 13px
      fontWeight: "400"
      lineHeight: 1.5
      letterSpacing: 0px
  spacing:
    xs: 4px
    sm: 8px
    md: 16px
    lg: 24px
    xl: 32px
    2xl: 48px
---

# AntiVibe Design System

Dark-first security tool dashboard. Cyber-industrial aesthetic.

## Colors

### Backgrounds
- **Background**: `#0A0B0D` — near black, slightly warm
- **Surface**: `#131517` — cards, elevated panels
- **Surface-hover**: `#1A1D20` — interactive hover states
- **Border**: `#23262A` — subtle borders, dividers

### Brand
- **Primary**: `#6366F1` — indigo, trust/intelligence
- **Primary-hover**: `#818CF8` — brighter indigo

### Severity
- **Critical**: `#EF4444` — red-500
- **High**: `#F59E0B` — amber-500
- **Medium**: `#EAB308` — yellow-500
- **Low**: `#3B82F6` — blue-500
- **Info**: `#6B7280` — gray-500

### Text
- **Text-primary**: `#F9FAFB` — headings, primary content
- **Text-secondary**: `#9CA3AF` — body text, descriptions
- **Text-muted**: `#6B7280` — labels, metadata, placeholders

## Typography

### Font Families
- **Sans**: Inter (Google Font) — UI text, headings, body
- **Mono**: JetBrains Mono (Google Font) — code, file paths, scan IDs, technical data

### Type Scale
- **H1**: 36px / 700 / 1.1 line-height
- **H2**: 24px / 600 / 1.2 line-height
- **H3**: 18px / 600 / 1.3 line-height
- **Body**: 15px / 400 / 1.6 line-height
- **Small**: 13px / 400 / 1.5 line-height
- **Label**: 12px / 500 / uppercase / 0.05em letter-spacing

## Spacing

4px base grid:
- **xs**: 4px
- **sm**: 8px
- **md**: 16px
- **lg**: 24px
- **xl**: 32px
- **2xl**: 48px

## Border Radius

- **sm**: 6px — small elements, badges
- **md**: 10px — cards, inputs
- **lg**: 14px — large panels, modals
- **full**: 9999px — pills, circular buttons

## Shadows

- **card**: `0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)` — default card elevation
- **elevated**: `0 4px 12px rgba(0,0,0,0.4)` — hover states, dropdowns
- **glow-red**: `0 0 20px rgba(239,68,68,0.15)` — critical severity glow
- **glow-indigo**: `0 0 20px rgba(99,102,241,0.15)` — primary action glow

## Animations

- **Input focus**: border transitions to indigo over 200ms
- **Button hover**: indigo brightens, scale 1.02 over 150ms
- **Progress pulse**: opacity 0.6 → 1.0 → 0.6, 2s loop
- **Card stagger**: fade-in 50ms delay per card, max 300ms total
- **Card expand**: height + opacity 250ms ease-out
- **PoC reveal**: slide-down 200ms

## Component Patterns

### Severity Badge
Colored pill with severity label. Background uses severity color at 15% opacity, text at full color.

### Finding Card
- Left border: 4px severity color
- Expandable: click → slide-down detail panel
- Code snippet: mono font, dark bg, line highlight
- PoC section: toggle reveal with curl command

### Progress Stepper
Horizontal steps: Queued → Cloning → Analyzing → Sandbox → Complete
- Active step: indigo pulse animation
- Completed step: green check
- Pending step: gray circle

## Visual Style

- Dark bg `#0A0B0D`, indigo accents, severity colors pop
- Glassmorphism subtle (backdrop-blur on cards)
- Monospace accents for technical data
- Generous whitespace, not cramped
- No external icon libraries — all SVGs inline
- No external animation libraries — CSS transitions only
