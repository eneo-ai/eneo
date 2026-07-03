# Product

## Register

product

## Users

Swedish public-sector municipality workers — business developers, operations
developers, and everyday municipal employees getting started with AI. They are
domain experts in municipal operations, **not** developers; technical proficiency
spans complete beginners to power users.

Context of use: desktop-first, at office workstations, during work hours. The job
to be done is turning AI into practical operational tooling — building and running
AI assistants, managing knowledge collections, composing multi-step flows, and
setting up triggers — without ever feeling like they are using a developer tool.
The `Användare` / `Avancerad` (User / Advanced) mode split keeps the interface
simple by default and reveals power only on demand.

## Product Purpose

Eneo is a democratic AI platform for the public sector — open, transparent, and
governed, running on infrastructure the organization controls. The web GUI is
where municipal staff make AI part of everyday work: assistants, knowledge bases,
flows (multi-step AI workflows), and triggers.

It exists so public-sector organizations can adopt AI responsibly instead of
depending on opaque consumer tools. Success looks like a municipal employee with
no AI background independently building something genuinely useful — and trusting
that it operates within clear governance boundaries.

## Brand Personality

**Trustworthy · calm · professional.** The voice is measured and reassuring — a
well-maintained public institution, not a startup. Emotionally, users should feel
in control and never overwhelmed, and should trust that AI is being used
responsibly and within governance. This mirrors Swedish public-sector values:
transparency, reliability, democratic accountability.

It should never read as flashy startup energy, a dark-mode developer tool, or a
playful consumer AI app. No "magic" metaphors — serious tooling for serious work
that still never intimidates.

## Anti-references

- Generic admin dashboards and Material Design sameness.
- Consumer AI apps with gradient-heavy, "magical" aesthetics.
- Dark-mode-first, developer-centric IDE aesthetics. Linear / Vercel are a **craft**
  benchmark (polish, information density, micro-detail) — adopt their quality, not
  their dark developer look.
- Glassmorphism, neon accents, dark-mode-as-default.
- Anything that makes a non-technical municipal employee feel they have wandered
  into a developer tool.

## Design Principles

1. **Calm confidence over flashy capability.** Every interaction feels measured
   and reliable; motion is purposeful, never decorative.
2. **Progressive disclosure is the architecture.** Simple by default, powerful on
   demand (`Användare` / `Avancerad`). Never front-load complexity.
3. **Warm professionalism.** Restrained and functional with warm undertones — the
   feeling of a trustworthy, well-run institution rather than a cold utility.
4. **Improve, don't preserve.** The melt-ui → shadcn-svelte migration is a design
   upgrade: each migrated surface should feel more polished than what it replaced,
   not a pixel-match of the old design.
5. **Respect the context.** Municipal domain experts, not developers — clear
   labels, forgiving interactions, and guiding empty states over terse power-user
   affordances.

## Accessibility & Inclusion

Target **WCAG 2.2 AA** across the app — a superset of the EU Web Accessibility
Directive / EN 301 549 baseline that binds Swedish public-sector services. In
practice this means: visible keyboard focus and full keyboard operability, correct
semantics/ARIA on custom controls (menus, selects, dialogs, disclosures), body
contrast ≥ 4.5:1 (≥ 3:1 for large text and UI boundaries), honoring
`prefers-reduced-motion`, and never signaling state through color alone.

All user-facing text carries `sv` / `en` translation keys (Paraglide); Swedish is
the primary language. The experience is desktop-first but layouts must stay usable
at smaller widths. Because users range from first-time to expert, the default
`Användare` mode must remain legible and low in cognitive load.
