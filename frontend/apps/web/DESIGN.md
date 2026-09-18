# Eneo product interface

## Overview

Eneo uses a compact, calm interface for builders and organisation administrators.
Extend the existing Svelte 5 and shadcn-svelte components. Product actions,
resource ownership, and their consequences should be easy to scan.

## Colors

The canonical tokens are in `../../packages/ui/src/styles/` and mapped in
`src/app.css`. Use semantic foreground, muted foreground, background, border,
accent, and destructive tokens so controls follow the user's theme. Filled
controls use `bg-accent-default` and `text-on-fill`; `bg-primary` has a legacy
namespace conflict described in `src/app.css`.

## Typography

Retain the shared Inter/sans stack. Existing administration tables use small
body text, medium-weight resource names, muted secondary information, and
tabular numerals for dates and counts. Long descriptions and translated labels
must wrap without covering adjacent controls.

## Layout

Use the shared `Page` shell. Skills pages use a centred content area, closely
grouped search/actions, and responsive tables. At narrow widths, move secondary
information below the resource name while keeping important status and actions
available. English and Swedish share the same layout.

## Elevation & Depth

Use existing subtle borders and neutral surfaces. Reserve overlays for actions
that require confirmation. Avoid introducing new decorative cards or animation.

## Components

Reuse `Button`, `Checkbox`, `Table`, `Badge`, `Alert`, `AlertDialog`, `Field`, and
`InputGroup` from `src/lib/components/ui/`. Keep visible labels, keyboard focus,
pending states, recoverable errors, and clear confirmation of destructive actions.
Bulk actions describe the selected resources and retain selection after failure.
