import { RuleTester } from "eslint";
import tsParser from "@typescript-eslint/parser";

import rule from "./no-weak-focus-indicator.js";

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
    sourceType: "module",
  },
});

const translucent = (token) => ({
  messageId: "translucentRing",
  data: { token },
});
const removed = (token) => ({ messageId: "outlineRemoved", data: { token } });

const RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

ruleTester.run("no-weak-focus-indicator", rule, {
  valid: [
    // The full-strength ring.
    { code: `<button className="${RING}" />` },
    // outline-none with a replacement in the same string, list or helper call.
    {
      code: '<button className="outline-none focus-visible:ring-2 focus-visible:ring-ring" />',
    },
    {
      code: `<input className={cn("outline-none", "${RING}", className)} />`,
    },
    {
      code: `const button = cva("inline-flex outline-none", { variants: { variant: { default: "${RING}" } } });`,
    },
    {
      code: '<div className={open ? "outline-hidden focus-visible:outline-2" : "focus-visible:outline-2 outline-hidden"} />',
    },
    {
      code: '<div className={`outline-none ${active ? "focus-within:outline-2" : ""}`} />',
    },
    {
      code: '<input className="focus:outline-none focus:ring-2 focus:ring-ring" />',
    },
    {
      code: '<div className="has-[input:focus-visible]:outline-2 [&_input]:outline-none" />',
    },
    // Script-only focus targets (skip link target, headings) need no ring.
    {
      code: '<main id="main-content" tabIndex={-1} className="focus:outline-none" />',
    },
    { code: '<h2 tabIndex={-1} className="outline-none">Titel</h2>' },
    { code: '<h2 tabIndex="-1" className="outline-none">Titel</h2>' },
    {
      code: '<h2 tabIndex={focusTitle ? -1 : undefined} className={cn("font-semibold outline-none", className)} />',
    },
    // Opaque rings, ring offsets and decorative translucent rings are fine.
    {
      code: '<button className="focus-visible:ring-2 focus-visible:ring-ring" />',
    },
    { code: '<div className="ring-1 ring-black/5" />' },
    { code: '<div className="aria-invalid:ring-destructive/20" />' },
    { code: '<div className="focus-visible:ring-offset-background/50" />' },
  ],
  invalid: [
    // The legacy shadcn halo.
    {
      code: '<button className="outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" />',
      errors: [translucent("focus-visible:ring-ring/50")],
    },
    {
      code: '<div className="has-[[data-slot=control]:focus-visible]:ring-ring/50" />',
      errors: [
        translucent("has-[[data-slot=control]:focus-visible]:ring-ring/50"),
      ],
    },
    {
      code: '<button className="focus-visible:outline-ring/40 focus-visible:outline-2" />',
      errors: [translucent("focus-visible:outline-ring/40")],
    },
    {
      code: '<button className="focus-visible:ring-2 focus-visible:ring-destructive/20" />',
      errors: [translucent("focus-visible:ring-destructive/20")],
    },
    // ring-ring is the focus colour: translucent anywhere is a weak focus ring.
    {
      code: "const halo = 'ring-ring/50';",
      errors: [translucent("ring-ring/50")],
    },
    // Outline removed without a replacement.
    {
      code: '<button className="outline-none" />',
      errors: [removed("outline-none")],
    },
    {
      code: '<div role="option" className="outline-hidden focus:bg-accent" />',
      errors: [removed("outline-hidden")],
    },
    {
      code: '<textarea className="resize-none focus:outline-none" />',
      errors: [removed("focus:outline-none")],
    },
    {
      code: '<input className={cn("h-9 outline-none!", className)} />',
      errors: [removed("outline-none!")],
    },
    {
      code: 'const ITEM = "flex items-center outline-hidden";',
      errors: [removed("outline-hidden")],
    },
    {
      code: 'const item = cva("flex outline-none", { variants: { tone: { muted: "focus-visible:ring-ring/50" } } });',
      errors: [
        removed("outline-none"),
        translucent("focus-visible:ring-ring/50"),
      ],
    },
    // A width alone (focus-visible:outline-offset-2) or a colour is no ring.
    {
      code: '<button className="outline-none focus-visible:outline-offset-2 focus-visible:ring-ring" />',
      errors: [removed("outline-none")],
    },
    {
      code: '<button className="outline-none focus-visible:ring-0" />',
      errors: [removed("outline-none")],
    },
    // Controls Tab reaches still need a ring, whatever their tabIndex branch.
    {
      code: '<button tabIndex={active ? 0 : -1} className="outline-none" />',
      errors: [removed("outline-none")],
    },
    {
      code: '<button tabIndex={disabled ? -1 : undefined} className="outline-none" />',
      errors: [removed("outline-none")],
    },
    {
      code: '<span tabIndex={0} className="outline-none" />',
      errors: [removed("outline-none")],
    },
    // A literal outside a className or class helper is its own class list.
    {
      code: '<button className={cn(styles("outline-none"), "focus-visible:ring-2")} />',
      errors: [removed("outline-none")],
    },
  ],
});
