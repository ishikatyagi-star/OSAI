# OSAI Design System

> Frontend lane (S2). This documents the visual language and component system used
> across `osai-web/`. The goal: every new screen should feel native to OSAI without
> re-deciding colors, spacing, or component behavior.

## Foundations

OSAI is a **dark-first** product. The aesthetic is calm, dense, and technical —
near-black surfaces, a single teal accent, and restrained use of color for status.

### Color tokens

Defined once in `app/globals.css` (`:root`) and mirrored into shadcn/Tailwind tokens
in `app/theme.css`. Always reference tokens — never hardcode hex in components.

| Token | Value | Use |
|---|---|---|
| `--bg` / `background` | `#0a0a0a` | App background |
| `--bg-surface` / `card` | `#111111` | Cards, sidebar, panels |
| `--bg-elevated` / `popover` | `#1a1a1a` | Menus, tooltips, raised surfaces |
| `--teal` / `primary` | `#00c896` | Primary actions, active state, focus |
| `--text-primary` / `foreground` | `#f0f0f0` | Primary text |
| `--text-secondary` / `muted-foreground` | `#888888` | Secondary text |
| `--border` | `rgba(255,255,255,0.08)` | Hairline borders |
| `--red` / `destructive` | `#ff4d4d` | Errors, failed, destructive |
| `--orange` | `#ff8c42` | Warnings / tickets |
| `--yellow` / `warning` | `#f5c842` | Caution, "needs review" |
| `--blue` / `info` | `#4d9fff` | Informational / projects |
| `--purple` | `#a855f7` | Decisions |

Status colors map consistently across the product:
**green = done/pass**, **yellow = needs review/partial**, **red = failed/breach**,
**blue = info/project**, **purple = decision**, **orange = ticket**.

### Typography

- **Sans:** Inter (`--font`) — all UI text.
- **Mono:** JetBrains Mono (`--font-mono`) — IDs, keys, metadata, code-like values.
- Base size 14px; secondary/meta text 11–12px.

### Spacing & radius

- 4px base grid (gaps of 1.5/2/3/4 in Tailwind = 6/8/12/16px).
- Radius: `--radius` = 0.5rem; cards `rounded-lg`, chips/buttons `rounded-md`,
  chat bubbles `rounded-2xl`.

## Component system: shadcn/ui

New UI uses **shadcn/ui** (Radix + Tailwind), themed to the tokens above.

- Tailwind v4 is imported in `app/theme.css` **without preflight**, so it coexists
  with the hand-written class-based CSS in `globals.css` (sidebar, topbar, tables,
  etc.) without resetting it.
- shadcn tokens (`primary`, `card`, `muted-foreground`, `border`, …) are mapped 1:1
  to the OSAI palette, so primitives look native out of the box.
- Primitives live in `components/ui/`: `button`, `card`, `input`, `textarea`,
  `badge`, `separator`, `skeleton`, `tabs`, `scroll-area`, `tooltip`.
- Use `cn()` from `lib/utils.ts` to compose/override classes.

### Adding a shadcn component

`components.json` is configured (style: new-york, RSC, CSS at `app/theme.css`). Add
more primitives with the shadcn CLI, then re-theme any hardcoded colors to OSAI tokens:

```bash
npx shadcn@latest add dropdown-menu
```

## Patterns

- **Icons:** `lucide-react`, sized via `size-4` (16px) inline; legacy glyph icons
  (◈ ⬡ ⚡) remain in the sidebar for continuity.
- **Badges:** use semantic variants (`success`/`warning`/`destructive`/`info`/`muted`)
  rather than ad-hoc colors.
- **Citations & provenance:** anything sourced from a connector shows the connector
  icon+color from `lib/connector-meta.ts`. Graph entity types use `lib/graph-meta.ts`.
- **Full-height screens** (Ask, Org Graph): use `h-[calc(100vh-128px)]` (the content
  box inside the 52px topbar and main padding) with an internal scroll region and a
  pinned footer/composer.
- **Live-vs-demo:** data screens try the live API and fall back to demo data,
  surfacing a `demo data` badge when the fallback is active.

## Accessibility

- Maintain visible focus rings (`focus-visible:ring-ring`).
- Color is never the only signal — pair status colors with icons/labels
  (e.g. eval pass/fail uses a check/x icon, not just green/red).
