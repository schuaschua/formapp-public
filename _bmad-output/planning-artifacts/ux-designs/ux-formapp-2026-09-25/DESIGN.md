---
name: formapp
description: 'Agent-first life insurance proposal form. Laptop web app where an insurance agent chats with an AI that fills in the form. Theme E "Forest": a solid deep forest-green header over a light grey/white canvas, flat white cards with a subtle shadow (no glass, no glow).'
status: final
updated: 2026-09-28
sources:
  - ../../../specs/spec-agent-first-insurance-form/SPEC.md
  - ../../architecture/architecture-formapp-2026-09-25/ARCHITECTURE-SPINE.md
colors:
  # Forest palette (Theme E), replacing the crimson palette of Theme D.
  # Style mood sampled from imports/forest-theme-reference.png (owner-shared Dribbble
  # shot, style-only reference -- see Brand & Style). White stays a primary colour.
  white: '#FFFFFF'
  forest: '#123B34'          # deep forest green: header bar, brand, primary button, current page, user chat bubble
  forest-dark: '#0B2622'     # forest x0.72; gradient end, hover/pressed, selected rating digit
  forest-accent: '#1B6E52'   # interactive green: focus ring, selected radio/segment, links, completion check
  forest-accent-dark: '#145440' # forest-accent x0.75; text on forest tint, submitted chip text
  amber: '#FDBB2F'           # unchanged: problem/attention highlight only
  red: '#EE1B2E'             # unchanged: system failures only
  steel-blue: '#7BAABE'      # unchanged: info note ("AI is filling in answers...")
  steel-blue-dark: '#445E69' # unchanged: info note text/label
  # Neutrals (re-picked with a faint green-grey cast to sit with forest)
  ink-heading: '#16241F'
  ink-body: '#3A4A44'
  ink-secondary: '#63706A'   # also used for field placeholders
  grey-mid: '#8B968F'        # Cancel button border, empty rating stars
  light-grey: '#C7CCC8'      # AI chat bubble border, divider-strong
  # Surfaces (flat, no glass/blur)
  canvas: '#F5F6F4'          # app background
  card: '#FFFFFF'            # flat white card: header, page menu, form, chat, lists, modal
  field: '#F3F4F4'           # text input / select fill
  field-read-only: '#ECEEEC'
  # Lines
  border-field: '#DCE0DC'    # subtle; fields are identified primarily by fill + icon, not border (see WCAG notes)
  border-locked: '#B7C0BB'   # dashed, read-only field edge
  divider: '#E4E6E3'         # hairline between form rows
  divider-strong: '#C7CCC8'  # table header rule
  menu-line: '#E4E6E3'
  # Tints
  forest-tint: '#E7F1EC'     # forest-accent 12%: selected rating tile, submitted chip, toast pill edge tint
  forest-border: '#1B6E5273' # forest-accent 45%: submitted-strip / chip border
  amber-tint-row: '#FDBB2F4D'   # amber 30%, question problem fill (unchanged)
  amber-tint-menu: '#FDBB2F33'  # amber 20%, menu problem box fill (unchanged)
  steel-tint-note: '#7BAABE38'  # steel-blue 22%, info note / typing dots (unchanged)
  draft-chip: '#3A4A4414'       # ink-body 8%
  tab-track: '#3A4A4412'        # ink-body 7%
  forest-tint-select: '#1B6E5212' # forest-accent 7%, selected rating tile fill
  red-tint-banner: '#EE1B2E14'  # red 8%, system-failure banner fill (unchanged)
  scrim: '#16241F8C'            # ink-heading 55%, modal scrim (was crimson-toned ink-heading scrim in Theme D, same alpha)
typography:
  # System stack everywhere: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
  display:
    fontFamily: system-ui
    fontSize: 56px
    fontWeight: '800'
    lineHeight: '1'
    letterSpacing: -0.035em
  headline-lg:
    fontFamily: system-ui
    fontSize: 30px
    fontWeight: '800'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: system-ui
    fontSize: 24px
    fontWeight: '800'
    lineHeight: '1.05'
    letterSpacing: -0.02em
  modal-body:
    fontFamily: system-ui
    fontSize: 19px
    fontWeight: '400'
    lineHeight: '1.5'
  declaration:
    fontFamily: system-ui
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1.45'
  toast:
    fontFamily: system-ui
    fontSize: 19px
    fontWeight: '700'
  list-name:
    fontFamily: system-ui
    fontSize: 18px
    fontWeight: '700'
  body:
    fontFamily: system-ui
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.45'
  menu-item:
    fontFamily: system-ui
    fontSize: 15px
    fontWeight: '400'
  button:
    fontFamily: system-ui
    fontSize: 15px
    fontWeight: '700'
  question:
    fontFamily: system-ui
    fontSize: 16px
    fontWeight: '600'
    lineHeight: '1.35'
  chat:
    fontFamily: system-ui
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.4'
  answer:
    fontFamily: system-ui
    fontSize: 16px
    fontWeight: '400'
  section-label:
    fontFamily: system-ui
    fontSize: 14px
    fontWeight: '800'
    letterSpacing: 0.02em
  caption:
    fontFamily: system-ui
    fontSize: 14px
    fontWeight: '700'
  overline:
    fontFamily: system-ui
    fontSize: 14px
    fontWeight: '700'
    letterSpacing: 0.06em
  untitled-name:
    fontFamily: ui-monospace
    fontSize: 16px
    fontWeight: '600'
rounded:
  sm: 8px
  md: 12px
  lg: 16px
  header: 18px
  xl: 20px
  xxl: 26px
  shell: 30px
  full: 9999px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 20px
  '6': 24px
  card-gap: 14px
  screen-padding: 20px
  header-height: 56px
  menu-width: 200px
  menu-rail-width: 64px
  row-height: 44px
  control-height: 36px
  list-row-height: 58px
  button-height: 40px
  modal-button-height: 52px
  modal-width: 640px
components:
  flat-card:
    background: '{colors.card}'
    border: 'none'
    radius: '{rounded.xl}'
  app-header:
    background: '{colors.forest}'
    radius: '0'
    height: '{spacing.header-height}'
    foreground: '{colors.white}'
  page-menu:
    background: '{colors.card}'
    width: '{spacing.menu-width}'
    text: '{colors.ink-heading}'
    muted: '{colors.ink-secondary}'
  page-menu-item-current:
    background: '{colors.forest}'
    foreground: '{colors.white}'
    radius: '{rounded.full}'
  page-menu-item-problem:
    background: '{colors.amber-tint-menu}'
    outline: '2px inset {colors.amber}'
    radius: '{rounded.md}'
    badge: '{colors.amber}'
    badge-foreground: '{colors.ink-heading}'
  page-menu-rail:
    background: '{colors.card}'
    width: '{spacing.menu-rail-width}'
    done-dot: '{colors.forest-accent}'
    problem-dot: '{colors.amber}'
  completion-check:
    foreground: '{colors.forest-accent}'
  progress-bar:
    track: '{colors.menu-line}'
    fill: 'linear-gradient(90deg, {colors.forest}, {colors.forest-dark})'
  question-row:
    label: '{typography.question}'
    divider: '{colors.divider}'
    min-height: '{spacing.row-height}'
  section-heading:
    foreground: '{colors.forest-accent}'
    typography: '{typography.section-label}'
  text-input:
    height: '{spacing.control-height}'
    background: '{colors.field}'
    border: '1px solid {colors.border-field}'
    radius: '{rounded.sm}'
    foreground: '{colors.ink-body}'
  segmented-choice:
    background: '{colors.field}'
    selected-background: '{colors.forest}'
    selected-foreground: '{colors.white}'
    radius: '{rounded.full}'
  field-read-only:
    background: '{colors.field-read-only}'
    border: '1px dashed {colors.border-locked}'
    selected-background: '{colors.ink-secondary}'
  problem-highlight:
    background: '{colors.amber-tint-row}'
    underline: '2px solid {colors.amber}'
    radius: '{rounded.sm} {rounded.sm} 0 0'
    badge: '{colors.amber}'
    badge-foreground: '{colors.ink-heading}'
    message: '{colors.ink-heading}'
  info-note:
    background: '{colors.steel-tint-note}'
    foreground: '{colors.steel-blue-dark}'
    radius: '{rounded.full}'
  button-primary:
    background: 'linear-gradient(145deg, {colors.forest}, {colors.forest-dark})'
    foreground: '{colors.white}'
    radius: '{rounded.full}'
    height: '{spacing.button-height}'
  button-secondary:
    background: '{colors.card}'
    border: '1.5px solid {colors.forest}'
    foreground: '{colors.forest}'
    radius: '{rounded.full}'
  button-cancel:
    border: '1.5px solid {colors.grey-mid}'
    foreground: '{colors.ink-body}'
    radius: '{rounded.full}'
  button-destructive:
    background: '{colors.red-tint-banner}'
    border: '2px solid {colors.red}'
    foreground: '{colors.ink-heading}'
    radius: '{rounded.full}'
  button-disabled:
    opacity: '0.42'
    shadow: 'none'
  save-status:
    typography: '{typography.caption}'
    foreground: '{colors.ink-secondary}'
    check: '{colors.forest-accent}'
  system-error-banner:
    background: '{colors.red-tint-banner}'
    border: '2px solid {colors.red}'
    icon: '{colors.red}'
    foreground: '{colors.ink-heading}'
    radius: '{rounded.md}'
  skeleton-row:
    background: '{colors.field-read-only}'
    radius: '{rounded.sm}'
  submitted-strip:
    background: '{colors.forest-tint}'
    border: '1px solid {colors.forest-border}'
    foreground: '{colors.forest-accent-dark}'
    radius: '{rounded.full}'
  avatar-menu:
    background: '{colors.card}'
    radius: '{rounded.md}'
    foreground: '{colors.ink-heading}'
  chat-panel:
    background: '{colors.card}'
    radius: '{rounded.xl}'
  chat-bubble-user:
    background: 'linear-gradient(145deg, {colors.forest}, {colors.forest-dark})'
    foreground: '{colors.white}'
  chat-bubble-ai:
    background: '{colors.field}'
    border: '1px solid {colors.light-grey}'
    foreground: '{colors.ink-body}'
    label: '{colors.steel-blue-dark}'
  chat-input:
    background: '{colors.field}'
    border: '1px solid {colors.border-field}'
    radius: '{rounded.full}'
    height: '{spacing.button-height}'
  send-button:
    background: 'linear-gradient(145deg, {colors.forest}, {colors.forest-dark})'
    foreground: '{colors.white}'
    radius: '{rounded.full}'
  mic-button:
    background: 'linear-gradient(145deg, {colors.forest}, {colors.forest-dark})'
    foreground: '{colors.white}'
    radius: '{rounded.full}'
  send-button-wait:
    background: '{colors.field-read-only}'
    foreground: '{colors.ink-body}'
    border: '1px solid {colors.grey-mid}'
  tabs:
    track: '{colors.tab-track}'
    selected-background: '{colors.ink-heading}'
    selected-foreground: '{colors.white}'
    radius: '{rounded.full}'
  proposal-list-row:
    name: '{typography.list-name}'
    min-height: '{spacing.list-row-height}'
    divider: '{colors.divider}'
  status-chip-draft:
    background: '{colors.draft-chip}'
    foreground: '{colors.ink-body}'
    radius: '{rounded.full}'
  status-chip-submitted:
    background: '{colors.forest-tint}'
    border: '1px solid {colors.forest-border}'
    foreground: '{colors.forest-accent-dark}'
    radius: '{rounded.full}'
  modal:
    background: '{colors.card}'
    radius: '{rounded.xxl}'
    width: '{spacing.modal-width}'
    scrim: '{colors.scrim}'
  declaration-box:
    background: '{colors.field-read-only}'
    border: '1px solid {colors.border-field}'
    radius: '{rounded.lg}'
    typography: '{typography.declaration}'
  rating-tile:
    background: '{colors.white}'
    border: '1.5px solid {colors.grey-mid}'
    star: '{colors.light-grey}'
    star-filled: '{colors.forest-accent}'
    selected-background: '{colors.forest-tint-select}'
    selected-border: '{colors.forest-accent}'
    selected-foreground: '{colors.forest-accent-dark}'
    radius: '{rounded.lg}'
  toast-success:
    background: '{colors.card}'
    border: '1px solid {colors.forest-border}'
    icon: '{colors.forest-accent}'
    radius: '{rounded.full}'
  welcome-card:
    radius: '{rounded.shell}'
    inner-radius: '22px'
  floating-chip:
    background: '{colors.card}'
    radius: '{rounded.lg}'
---

# formapp — Design Spine

Visual reference mockups live in [`mockups/`](./mockups/). This spine and [EXPERIENCE.md](./EXPERIENCE.md) win on any conflict with a mockup or import.

## Brand & Style

formapp is a work tool for insurance agents, many of them older and not comfortable with software. It has to feel trustworthy and corporate, calm and readable rather than showy. The chosen look is **Theme E, "Forest"**: a solid deep forest-green header sits above a very light grey/white canvas holding flat white cards with a subtle shadow. There is no glass, no blur and no glow — depth comes from a single soft shadow, not from translucency over colour.

**Owner decision (owner, 2026-09-27):** Theme D "Crimson glow" is retired. Its glass/glow surfaces and crimson brand colour are replaced by Theme E "Forest" end to end (welcome, lists, workspace). Layout, spacing, type sizes, the 16px minimum body size and the 200% zoom requirement are unchanged — this is a re-theme, not a redesign.

**Reference used, style only.** [imports/forest-theme-reference.png](./imports/forest-theme-reference.png) is a screenshot the owner shared, originating from a Dribbble shot ("Walker Wealth", an estate-planning intake form): <https://cdn.dribbble.com/userupload/46636490/file/e3ac59ddbb8f53dee5723100d214fd8b.jpg>. It is a third-party design and formapp takes **only its visual style** from it — the deep forest-green header mood, the flat white card on a light canvas, and the grey filled-field treatment (rounded corners, leading icon, grey placeholder). formapp does **not** reuse its logo, the "Walker Wealth" name, any of its copy, or its layout; formapp keeps its own name, wordmark, copy and the layout already decided below (page menu + form + chat workspace, split welcome card, proposal lists).

The three references that shaped Theme D remain the structural basis for layout (they are about arrangement, not colour, and are superseded on colour only):

- [imports/login-reference.png](./imports/login-reference.png): split welcome card, form on the left, lifestyle photo with floating chips on the right, pill buttons, large corners. Used for the welcome page only.
- [imports/form-reference.png](./imports/form-reference.png) ([webp](./imports/form-reference.webp)): app shell with a left page menu and a form card. Used for the proposal workspace.
- [imports/glass-reference.png](./imports/glass-reference.png) ([small](./imports/glass-reference-small.png)): separate floating rounded cards with gaps, bold headings, pill buttons. The frosted-glass treatment itself is retired with Theme D; the card separation, gaps and pill buttons carry forward.

## Colors

One palette throughout: the Forest greens plus white as a primary colour, with amber and red kept exactly as before for their semantic roles, and steel-blue kept for the info note. Derived shades exist only to pass contrast.

| Token | Hex | Used for | Not used for |
|---|---|---|---|
| `{colors.forest}` | #123B34 | Header bar, brand. Primary buttons (gradient to `{colors.forest-dark}`), current page in the menu, user chat bubbles, logo tile | Errors or warnings |
| `{colors.forest-dark}` | #0B2622 | Gradient end, hover/pressed, selected rating digit | Large fills on its own |
| `{colors.forest-accent}` | #1B6E52 | Interactive green: focus ring, selected segment/radio, section headings, links, completion ✓, filled rating stars | Header background (too light against white header text at header scale — header stays `{colors.forest}`) |
| `{colors.forest-accent-dark}` | #145440 | Text on forest tint (submitted chip, rating selected digit) | |
| `{colors.white}` | #FFFFFF | Card surfaces, fields sit on it, text on forest | |
| `{colors.canvas}` | #F5F6F4 | App background | |
| `{colors.card}` | #FFFFFF | Header (forest, not card), page menu, form, chat, lists, modal — every surface is a flat card, no glass | |
| `{colors.ink-heading}` | #16241F | Headings, question labels, problem messages, text on amber, selected tab and yes/no fill | |
| `{colors.ink-body}` | #3A4A44 | Body text, answer values | |
| `{colors.ink-secondary}` | #63706A | Secondary text, column headers, field placeholders, menu numbers | Answer values |
| `{colors.amber}` | #FDBB2F | "Needs your attention": problem outline on menu pages, problem underline on answers, the `!` badge. Unchanged from Theme D | Text colour. Amber is never used alone (see WCAG notes) |
| `{colors.red}` | #EE1B2E | System failures only: a save that failed, a lost connection. Always the outline plus a red `!` icon on the failure banner (`{components.system-error-banner}`). Unchanged from Theme D | Anything the agent must answer or fix on the form (that is amber). Never used as text colour |
| `{colors.steel-blue}` / `{colors.steel-blue-dark}` | #7BAABE / #445E69 | Info: "AI is filling in answers…" note, typing dots, "✦ formapp AI" label. Unchanged from Theme D | Focus ring (moved to `{colors.forest-accent}`) |
| `{colors.grey-mid}`, `{colors.light-grey}` | #8B968F, #C7CCC8 | Cancel button edge, empty rating stars, AI chat bubble border, dividers | |

**Completion check harmonised.** Theme D's separate olive/olive-dark "success" green is retired; completion ✓, the Submitted chip and the success-toast check now use `{colors.forest-accent}` / `{colors.forest-accent-dark}` so the whole app reads as one green family with the header, not two unrelated greens.

**No glow canvas.** Theme D's blurred crimson/slate/amber radial gradients behind every screen are removed. The canvas is a flat `{colors.canvas}`.

### WCAG notes

All pairs below are measured directly (flat colours, no composited glass), using the WCAG relative-luminance formula:

| Pair | Ratio |
|---|---|
| `{colors.ink-heading}` on card | 16.08 |
| `{colors.ink-body}` on card | 9.36 |
| `{colors.ink-secondary}` on card | 5.18 |
| Answer value (`ink-body`) on field | 8.50 |
| Placeholder (`ink-secondary`) on field | 4.70 |
| White on `{colors.forest}` (header, current page, user bubble, primary button) | 12.35 |
| White on `{colors.forest-dark}` (button gradient end) | 15.97 |
| `{colors.forest-accent}` text on card (secondary button, links, section heading) | 6.18 |
| `{colors.forest-accent}` on canvas | 5.70 |
| `{colors.forest-accent-dark}` on `{colors.forest-tint}` (submitted chip text) | 7.67 |
| Ink on amber tint | 13.67 |
| Info text `{colors.steel-blue-dark}` on steel tint | 5.01 (unchanged from Theme D) |
| `{colors.grey-mid}` vs white (Cancel border, non-text) | 3.06 |

Rules (unchanged from Theme D, harmonised to the new green):

- **Amber is never the only cue.** Every amber state pairs the amber tint with a dark `!` badge (`{colors.ink-heading}` on `{colors.amber}`) and, on the form, a text message ("Answer required"). Text on amber is always `{colors.ink-heading}`.
- **Red is for system failures only.** It means "the app has a problem" (save failed, connection lost), never "you have a problem" (that is amber). Red appears only as the banner outline and its `!` icon; the message text is `{colors.ink-heading}`.
- **Forest is not a status colour.** It is the brand and "current"/interactive colour. Never put an error or warning in forest green.
- Disabled buttons drop to 42% opacity (WCAG 1.4.3 inactive-component exemption) and always show why nearby (a note or the "Wait Ns" label).
- **Fields are identified by fill, not border contrast.** `{colors.border-field}` (#DCE0DC) measures only 1.3:1 against the white card, matching the reference's near-invisible field edge. This is a deliberate style choice, not an oversight: every field also carries a leading icon and a persistent label above it, and the focus state gets a clear `{colors.forest-accent}` ring at 5.6:1+ against the field fill. **Flagged as an assumption for Owner to review** — if stronger field boundaries are wanted regardless of the reference look, darken `{colors.border-field}` to reach 3:1 (e.g. #AEB6AF).

## Typography

Unchanged from Theme D. One system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`); no web fonts. Weight does the hierarchy: 800 for headings, 700 for buttons and labels, 600 for question labels.

**Minimum sizes (decided, for older users):**

- Answers, body text, questions and chat: at least 16px.
- Labels (menu items, buttons, section headings, captions, column headers): at least 14px. Nothing on screen is smaller.
- The app must stay usable at 200% browser zoom: nothing cut off, no sideways scrolling of the page. At that zoom the page menu drops to its rail and form rows stack the question above the answer.

| Token | Where |
|---|---|
| `{typography.display}` | "formapp" wordmark on the welcome page |
| `{typography.headline-lg}` | "My proposals", modal titles |
| `{typography.headline-md}` | Form page title ("5 · Health & lifestyle", the dot in `{colors.forest-accent}`) |
| `{typography.modal-body}`, `{typography.declaration}`, `{typography.toast}` | Modals and the success toast. Set larger than the workspace on purpose: these are the moments an older user must read carefully |
| `{typography.list-name}` | Customer name in proposal lists |
| `{typography.body}` | Default text; welcome tagline is 19px |
| `{typography.menu-item}` / `{typography.button}` | Page menu items / button labels |
| `{typography.caption}` | Small supporting text: dates in lists, "Saved ✓", problem messages |
| `{typography.question}` / `{typography.answer}` | Question label / answer value in form rows |
| `{typography.chat}` | Chat bubbles and input |
| `{typography.section-label}` | Section headings inside a page (e.g. "Gynaecology"), `{colors.forest-accent}` |
| `{typography.overline}` | Uppercase column headers ("Question", "Answer"), menu label "Pages" (0.08em) |
| `{typography.untitled-name}` | `Untitled_Proposal_NNN` in the Drafts list, monospace so it reads as a placeholder |

Dates use tabular numerals.

## Layout & Spacing

Unchanged from Theme D. Laptop only, designed at 1280×800. Spacing scale is 4-based (`{spacing.1}`…`{spacing.6}`); cards sit `{spacing.card-gap}` apart inside `{spacing.screen-padding}` of canvas.

**Proposal workspace** ([mockups/key-workspace.html](./mockups/key-workspace.html)): header row `{spacing.header-height}` in solid `{colors.forest}`, then the rest split 3:1 vertically.

- Top 3/4: page menu at 1/6 width (`{spacing.menu-width}` at 1280) + form card.
- Bottom 1/4: full-width chat card.

Form rows are two columns, question | answer (answer column 440px), one question per row, `{spacing.row-height}` minimum, hairline `{colors.divider}` between rows. Follow-up questions revealed by an answer are indented 18px under their parent. "Submit proposal" sits bottom right of the form card with the save status ("Saved ✓") to its left. There is no Save button: answers save on their own (see EXPERIENCE.md). The source-column layout in [mockups/provenance-columns-1.html](./mockups/provenance-columns-1.html) is kept only for its row style; its AI-assisted / Human-led columns are removed.

**My proposals** ([mockups/key-proposals.html](./mockups/key-proposals.html)): header + one large flat card. Title, Drafts/Submitted tabs and "+ New proposal" on one line; rows at `{spacing.list-row-height}` with columns name | status (170px) | date (220px) | chevron.

**Welcome** ([mockups/key-welcome.html](./mockups/key-welcome.html)): one split card centred on the canvas, left 0.92fr (wordmark, tagline, sign-in pill) and right 1.08fr (lifestyle photo with floating chips).

## Elevation & Depth

Depth comes from a single soft shadow on a flat white card over a light canvas — no glass, no blur, no glow.

- **Canvas**: flat `{colors.canvas}`, no gradients.
- **Flat card** (`{components.flat-card}`): `{colors.card}` fill, no border, one soft shadow: `0 1px 2px` ink-heading at 6% plus `0 8px 20px` ink-heading at 6%. Header, page menu, form, chat and list all use it, except the header which is solid `{colors.forest}` rather than white.
- **App header**: solid `{colors.forest}`, no shadow of its own (it sits at the very top); white logo mark and nav text.
- **Forest lift**: primary buttons, send button, current menu page and user bubbles cast a soft forest-tinted shadow (`0 6px 14px` forest at 24%) instead of the card shadow, so interactive/brand elements read as slightly raised.
- **Modal**: `{colors.card}` over a dark scrim (`{colors.scrim}`), no blur on the workspace behind (blur is a Theme D artefact); shadow `0 24px 70px` ink-heading at 35%.
- **Toast**: `{colors.card}` pill, shadow `0 16px 40px` ink-heading at 25%.
- **Read-only fields lose depth**: no shadow, flat `{colors.field-read-only}` fill, dashed edge.

## Shapes

Unchanged from Theme D. Big, soft corners everywhere. Nothing is sharp.

- `{rounded.full}`: every button, tab, menu item, chip, chat input, info note, yes/no control, toast.
- `{rounded.xl}` (20px): cards. `{rounded.header}` (18px): reserved, unused now the header is a full-width bar (see Do's and Don'ts).
- `{rounded.xxl}` (26px): modals. `{rounded.shell}` (30px): welcome split card (inner panels 22px).
- `{rounded.lg}` (16px): rating tiles, declaration box, floating chips. `{rounded.md}` (12px): the amber problem box on a menu page (squarer than the pill so the outline reads as a box).
- `{rounded.sm}` (8px): text inputs and selects in form rows.
- Chat bubbles are 18px with the tail corner at 6px (bottom right for user, bottom left for AI).

## Components

- **Flat card** — the base surface for the page menu, form, chat and lists. See Elevation & Depth. (Renamed from Theme D's "Glass card"; same rounding and layout role, flat fill instead of frosted glass.)
- **App header** — solid `{colors.forest}` bar, full width, no rounding, no shadow. Logo tile (forest-dark square, white "f", 10px corners) with "formapp" in white; breadcrumb in white at 75% opacity with the current item bold white ("Drafts / **Ally Macbeal**"); user avatar (forest-accent gradient circle, initial, 2px white ring) and name on the right in white. Clicking the avatar opens a small **avatar menu** (`{components.avatar-menu}`) below it, right-aligned, on a flat white card holding "Sign out".
- **Page menu** — label "Pages" + round collapse toggle (‹). Each item: numbered circle, page name, trailing marker. States:
  - current: `{colors.forest}` pill, white text, forest lift;
  - done: `{colors.forest-accent}` ✓ (**completion check**);
  - not started: muted text;
  - problem: `{rounded.md}` box, `{colors.amber-tint-menu}` fill, 2px `{colors.amber}` outline, trailing `!` badge;
  - current + problem: forest pill plus a 2.5px amber ring outside it and the `!` badge.
  A **progress bar** at the bottom: "3 of 5 pages done", 6px track, forest gradient fill.
- **Page menu rail** (collapsed menu, `{components.page-menu-rail}`) — the ‹ toggle shrinks the menu to a `{spacing.menu-rail-width}` flat-card rail; the toggle flips to ›. The rail shows one numbered circle per page: the current page is the forest circle, a done page has a small forest-accent ✓ dot at its corner, a problem page has a small amber dot with a dark `!`. Hovering or focusing a number shows the page name as a tooltip. No progress bar in the rail.
- **Question row** — label in `{typography.question}` `{colors.ink-heading}`; answer control on the right. Only question and answer: **no AI/human source markers of any kind.** Sub-questions indented and lighter (500 weight, `{colors.ink-body}`). **Section heading** rows span both columns in `{colors.forest-accent}` with a faint rule.
- **Answer controls** — text input and select (select has a ▾), `{spacing.control-height}` tall, `{rounded.sm}`, `{colors.field}` fill with a leading icon in `{colors.ink-secondary}` where the question suits one (matching the reference's field style); units ("cm", "kg") inside the field, right-aligned, secondary. Wide text box for details. **Segmented choice** for Yes/No and short option sets: pill track, selected option filled `{colors.forest}` with white text.
- **Read-only field** — `{colors.field-read-only}` fill, 1px dashed `{colors.border-locked}` edge, no shadow, not-allowed cursor; selected segment turns `{colors.ink-secondary}`. Used whenever the form is locked (AI reply, lock elsewhere, submitted).
- **Problem highlight** (from [imports/error-highlight-reference.png](./imports/error-highlight-reference.png), amber) — full answer-width `{colors.amber-tint-row}` band with 2px amber underline, the control on white inside it, trailing 18px `!` badge (dark ink on amber, thin dark ring); message below in bold `{colors.ink-heading}` `{typography.caption}` ("Answer required").
- **Info note** — pill in the form header: `{colors.steel-tint-note}` fill, steel border, `{colors.steel-blue-dark}` bold text, three fading dots when something is in progress ("AI is filling in answers…").
- **Buttons** — pills, 40px high (52px in modals), 700 weight.
  - Primary: forest gradient, white text, forest lift ("Submit proposal", "I agree", "+ New proposal", "Sign in with Microsoft").
  - Secondary: forest 1.5px outline and forest text on white card ("Retry", "Edit here instead").
  - Cancel: `{colors.grey-mid}` outline, body text.
  - Destructive (`{components.button-destructive}`): light red tint, 2px `{colors.red}` outline, `{colors.ink-heading}` text, the system failure banner's look. Only for "Delete draft" and its confirm; never for anything else.
  - Disabled: 42% opacity, no shadow.
- **Sign-in button** — primary, 52px, full width of the left panel (max 380px), with the four-square Microsoft glyph in white.
- **Chat panel** — flat card. Messages bottom-aligned. **User bubble**: forest gradient, white text, right. **AI bubble**: white field fill, light-grey border, left, prefixed "✦ formapp AI" in `{colors.steel-blue-dark}` 14px bold. While streaming: a thin caret plus steel typing dots. **Chat input**: 40px pill, placeholder in secondary ink; focus ring 2px `{colors.forest-accent}`, offset 2px. **Send button**: 40px forest circle with ↑. Disabled: `{colors.field-read-only}` fill, grey-mid border, secondary ↑. **Wait state**: the button widens to a pill reading "Wait 6s" in tabular numerals. **Mic button** (`{components.mic-button}`): the same 40px forest circle as Send, with a white microphone icon, directly left of Send; same disabled look as Send. **Listening**: while on (tap to start, tap again to stop), the mic widens to a forest pill reading "Listening" with the three fading dots of the info note, in white. Mic messages (blocked, unavailable, nothing heard) sit under the input in `{typography.caption}` `{colors.ink-secondary}`, never red.
- **Save status** (`{components.save-status}`) — small text left of "Submit proposal": "Saving…" while a save is in flight, then "Saved ✓" with the ✓ in `{colors.forest-accent}`. No button.
- **System failure banner** (`{components.system-error-banner}`) — full width across the top of the form card (or the list card): light red tint, 2px red outline, red `!` icon on the left, message in `{colors.ink-heading}`, a secondary "Retry" button on the right when retrying makes sense. The only place red appears.
- **Skeleton rows** (`{components.skeleton-row}`) — while a list or page loads, grey `{colors.field-read-only}` bars in the shape of the rows that are coming (name / chip / date in lists; question / answer in the form), gently pulsing. No spinners.
- **Tabs** — pill track (`{colors.tab-track}`); selected tab filled `{colors.ink-heading}`, white text. No counts.
- **Proposal list row** — name in `{typography.list-name}`, status chip, date ("Created 25 Sep 2026" / "Submitted 25 Sep 2026"), chevron ›. Newly submitted row gets a brighter white background. **Status chips**: pill with a leading dot; Draft = grey tint, body ink; Submitted = forest tint, forest border, forest-accent-dark text.
- **Empty state** — centred in the list card: 76px white rounded tile with a forest-outline document icon, "No drafts yet" in 22px/800, primary "+ New proposal" below.
- **Modal** — 640px, `{rounded.xxl}`, padding 34/38/30, over scrim. Title `{typography.headline-lg}`. Actions bottom right; Cancel left of the primary.
- **Declaration box** — the declaration sentence in `{typography.declaration}` inside a `{colors.field-read-only}` box with `{rounded.lg}`.
- **Rating tiles** — five equal tiles 64px high in a row, each a star over its number (1–5), no word labels. Stars up to the chosen value are `{colors.forest-accent}`, the rest light grey; the chosen tile gets a forest-accent border, forest tint, forest-accent-dark digit and a 3px forest-accent focus halo. Label "Rating (required)" with "(required)" in forest-accent-dark; "Comment (optional)" with "(optional)" in secondary. Comment box: white, 96px min, 14px corners.
- **Toast (success)** — centred near the bottom of the list screen: white pill, forest-accent border, 34px forest-accent circle with white ✓, `{typography.toast}` text.
- **Welcome card** — split flat-card shell (`{rounded.shell}`), white, single soft shadow, on the plain `{colors.canvas}`. Right: lifestyle photo (agent and customer at a table) with two **floating chips**: a proposal summary card and a forest chat bubble, each a small flat card with its own soft shadow. The mock uses an illustrated placeholder.
- **Build-time assets (decided, not open)** — the real welcome lifestyle photo and the Microsoft Entra company branding (logo, background image, colours on the Microsoft-hosted sign-in page) are picked by the build team at build time. They must fit this palette; nothing else in this spine depends on them.
- **Submitted strip** (`{components.submitted-strip}`) — pill across the top of the form card on a submitted proposal: forest tint, forest border, forest-accent-dark ✓ and "Submitted on <date>". Specified in words only; not mocked.
- **Other-window note** — the lock-elsewhere message uses the **info note** pill (`{components.info-note}`, no dots) with a secondary "Edit here instead" button beside it in the form header. Specified in words only; not mocked.

See the full set in [mockups/key-workspace.html](./mockups/key-workspace.html), [mockups/key-submit.html](./mockups/key-submit.html), [mockups/key-proposals.html](./mockups/key-proposals.html) and [mockups/key-welcome.html](./mockups/key-welcome.html).

## Do's and Don'ts

| Do | Don't |
|---|---|
| Put every surface on a flat white card with one soft shadow, over the plain light canvas | Use glass, blur or a glow/gradient canvas (Theme D is retired) |
| Use forest green for brand, primary actions and "current page" | Use forest green for errors, warnings or problem states |
| Pair amber with its tint, a dark `!` badge and a text message | Use amber alone, or amber text |
| Show system failures with a red outline + icon and dark message text | Write error messages in red, or use red for missing answers |
| Use the Destructive button only for deleting a draft | Use red for voice states or any other button |
| Keep answers and body text at 16px or more, labels at 14px or more | Copy the smaller sizes from the mockups |
| Show question + answer only on form rows | Show AI-assisted / Human-led columns, "filled by AI" chips or any provenance marker |
| Grey fill + dashed edge for every read-only answer | Hide or blank the form while it is locked |
| Pills for all buttons, tabs, chips and the chat input | Square or small-radius buttons |
| Make modal text larger than workspace text | Shrink declaration or rating text to fit |
| Keep one colour palette (Forest + amber/red/steel-blue) across welcome, lists and workspace | Introduce colours outside this set, or reintroduce crimson |
| Take only palette mood, flat-card and field styling from [imports/forest-theme-reference.png](./imports/forest-theme-reference.png) | Copy that reference's logo, "Walker Wealth" name, copy or layout — formapp keeps its own |
