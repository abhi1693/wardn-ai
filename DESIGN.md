# Wardn DESIGN.md

Wardn is an operational AI infrastructure product for teams that manage organizations,
workspaces, agents, MCP servers, secrets, provider credentials, guardrails, runtime sessions, and
resource limits.

The visual direction is inspired by Attio-style B2B workflow software: quiet, white, structured,
record-oriented, and built for repeated administrative work. Do not copy Attio screens or branding.
Use the same product-design language: precise information hierarchy, light chrome, fine borders,
compact controls, and calm surfaces that make dense operations easy to scan.

## Design Philosophy

Wardn should feel like a serious command surface, not a marketing site and not a generic dashboard.
The interface should make technical governance feel manageable: every page should help users answer
what exists, where it belongs, what state it is in, and what action is available next.

Prefer structured records over decorative cards. Prefer tables, lists, side panels, compact forms,
metadata rows, and status badges. Avoid oversized hero sections, one-page feature dumps, large
floating cards, strong gradients, decorative blobs, and illustration-led empty states.

The design should be visually quiet until state changes require attention. Use accent color for
focus, selection, links, and critical operational status. Do not use accent color as decoration.

## Color System

Use the CSS variables in `wardn/frontend/app/globals.css` as the source of truth.

### Core Surfaces

- `--background: #f7f8fa`
  - App background. Use for the page canvas behind the shell and content.
  - Rationale: a near-white gray separates the product frame from white records without making the
    app feel dark or heavy.
- `--card: #ffffff`
  - Primary record, table, form, popover, and shell surface.
  - Rationale: Wardn is data-heavy, so the main content should remain white and readable.
- `--muted: #f5f6f8`
  - Subtle table headers, hover states, disabled fields, icon wells, and low-emphasis containers.
  - Rationale: muted surfaces create hierarchy without shadows.
- `--border: #e5e7eb`
  - Default hairline border for cards, tables, controls, panels, separators, and nav selection.
  - Rationale: borders, not shadows, define structure.

### Text

- `--foreground: #171717`
  - Primary text, headings, key values, and selected navigation.
- `--muted-foreground: #6b7280`
  - Secondary labels, descriptions, timestamps, slugs, helper text, and unselected nav.
- Use black or near-black text sparingly for hierarchy. Avoid low-contrast gray on gray.

### Actions and Focus

- `--primary: #171717`
  - Primary buttons and highest-priority actions.
  - Rationale: primary actions should feel decisive without bright color noise.
- `--ring: #2563eb`
  - Focus rings, selected-border emphasis, links where needed, and interactive highlights.
  - Rationale: blue reads as utility and focus, not brand decoration.
- `--destructive: #d92d20`
  - Destructive actions and critical errors only.

### Status Colors

Use status color only when the state is meaningful:

- Success: emerald-50 background, emerald-200 border, emerald-700 text.
- Warning: amber-50 background, amber-200 border, amber-800 text.
- Error: red-50 background, red-200 border, red-700 text.
- Neutral: muted background, border, muted foreground.

Do not build pages around a single hue family. Wardn should read as a neutral product UI with
selective state colors.

## Typography

Use Inter as the default UI font:

- Body: 14px, 20px line height.
- Page titles: 18px, 24px line height, 600 weight.
- Section/card titles: 14px, 20px line height, 600 weight.
- Table headers: 12px, 16px line height, 500 weight.
- Metadata and helper text: 12px or 13px, muted foreground.
- Monospace: JetBrains Mono or system monospace at 13px for IDs, slugs, keys, code, and tokens.

Letter spacing should be `0`. Avoid uppercase tracking except for tiny metadata labels where the
existing component already uses it. Do not use large display typography inside dashboards, forms,
tables, cards, sidebars, or admin pages.

## Layout

### App Shell

The shell is a light product frame:

- Left sidebar: white surface, 252px desktop width, hairline right border.
- Header: 56px height, white translucent surface, bottom border.
- Content canvas: soft gray background with a max width around 1360px.
- Content padding: 24px desktop, 16px mobile.

Navigation should be compact. Active items use a pale blue-tinted background, fine border, and
medium text. Inactive items use muted text and a light hover background. Avoid dark rails and bright
active pills.

### Page Structure

Most product pages should follow this order:

1. App shell title and actions.
2. Optional compact summary strip or filter row.
3. Primary table or record list.
4. Detail/editor surface, secondary panel, or empty state.

Do not make a "landing page" inside the app. The first screen should be useful immediately.

### Density

Wardn is an operational tool. Use compact spacing:

- Page sections: 16px to 24px vertical gap.
- Tables: 44px row height unless content requires more.
- Form fields: 36px control height.
- Cards/panels: 16px internal padding by default.
- Icon wells: 32px square for ordinary records, 40px only for empty states or prominent summaries.

Avoid large 48px+ cards unless the page is genuinely a metric dashboard. Even then, keep metrics
restrained and aligned.

## Components

### Buttons

Buttons are compact and utilitarian:

- Default: near-black fill, white text, 36px height.
- Outline: white fill, border, foreground text.
- Secondary: muted fill, border, foreground text.
- Ghost: no border, muted text, muted hover background.
- Icon buttons: 32px square.

Use icons for tool actions whenever a lucide icon exists. Text buttons are for clear commands.
Avoid broad, rounded, marketing-style call-to-action buttons.

### Cards and Panels

Cards are for bounded records, tools, modals, repeated items, and editor surfaces. They are not for
wrapping every page section.

- Radius: 6px or 8px maximum.
- Border: default hairline border.
- Shadow: minimal `--shadow-card`, or none.
- Header: compact, border-bottom, 12px to 16px padding.
- Content: 16px padding.

Do not nest cards inside cards. Use separators, table rows, or field groups instead.

### Tables

Tables are the default for managed resources:

- Header background: muted or muted/70.
- Header text: 12px, muted, medium weight.
- Rows: 44px height, border-bottom, subtle hover.
- Cells: 12px horizontal padding.
- Primary cell should contain the readable name plus a muted monospace key/slug when useful.
- Actions should sit in a right-aligned compact column with icon buttons.

Do not replace a manageable table with a card grid unless the items are truly visual or spatial.

### Forms

Forms should feel like record editors:

- Use one or two columns depending on field count.
- Put labels close to fields.
- Keep helper text muted and short.
- For immutable fields, use read-only metadata rows or muted bordered values.
- Footer actions should be right-aligned in a subtle border-top action bar.

Avoid giant centered forms for admin workflows. If a form edits an existing resource, show the stable
record metadata above the editable fields.

### Lists and Records

Use record rows for objects like workspaces, agents, credentials, secrets, and server installs:

- Small icon well or service icon on the left.
- Name/title first.
- Slug, key, scope, or endpoint as muted metadata.
- Status badge and last-updated information where relevant.
- Actions on the right.

### Badges

Badges should be small, rectangular, and semantic. Do not use large pills as decoration. A badge
should communicate status, scope, visibility, install type, or risk.

### Empty States

Empty states should be useful but quiet:

- Small icon well.
- One concise title.
- One sentence of explanation.
- One primary action if creation is the next logical step.

Do not use illustrations or marketing copy in empty operational screens.

## Page Patterns

### Organization Pages

Organization-level pages should emphasize what applies across the organization:

- Workspaces
- Catalog sources
- LLM credentials
- API/agent tokens
- Limits
- Secret backends
- Organization settings

Never expose cross-organization selectors inside organization-scoped pages. The current organization
is determined by the route and shell context.

### Workspace Pages

Workspace-level pages should emphasize operational execution:

- Chat
- Workspace dashboard
- MCP server installations
- Runtime sessions
- Guardrails
- Workspace settings

Workspace pages may show the organization as context, but actions should target the current
workspace unless explicitly changing context.

### Limits UI

Limits are a governance registry, not a free-form key/value store:

- Show limits as a table first.
- Limit names should be readable; raw keys can appear as muted monospace metadata.
- Scope is implicit from the selected organization route and optional workspace target.
- Do not show global scope, user-id fields, custom keys, or cross-org selectors.
- Create/edit forms should use record-editor layout with target metadata and a compact action bar.

## Motion and Interaction

Use motion sparingly:

- Hover color changes are enough for most controls.
- Active states may use immediate background/border changes.
- Avoid scale animations except tiny icon movement in links.
- Avoid decorative animated backgrounds.

Focus states must be visible and use the ring token. Keyboard navigation should remain obvious.

## Accessibility

- Maintain readable contrast on all text.
- Icon-only buttons need accessible labels.
- Form fields need labels.
- Do not rely on color alone for destructive or success states.
- Tables need clear headers and predictable action placement.
- Text must fit within its container on mobile and desktop.

## Implementation Rules

- Prefer shared primitives in `wardn/frontend/components/ui/`.
- Use existing CSS variables from `wardn/frontend/app/globals.css`.
- Use lucide-react icons for UI actions and resource categories.
- Keep route-specific styling minimal; app-wide style belongs in shared primitives and shell.
- Use `Card` only for real panels, repeated records, modals, and tools.
- Prefer `Table` for managed-resource lists.
- Do not introduce gradient hero sections, decorative orbs, heavy shadows, or dark app chrome.
- Do not use beige, purple-gradient, dark-slate, or one-hue dominant themes.

## Rationale

Wardn manages sensitive, technical, multi-tenant infrastructure. The UI should reduce ambiguity and
make scope boundaries obvious. Attio-like structure gives Wardn a high-trust B2B feel without making
the product look like a sales page. The system relies on neutral surfaces, borders, compact records,
and semantic status so users can scan quickly and act confidently.
