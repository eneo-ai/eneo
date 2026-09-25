import { RuleTester } from "eslint";
import tsParser from "@typescript-eslint/parser";

import rule from "./no-literal-accessible-name.js";

const jsxRuleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2022,
    parserOptions: { ecmaFeatures: { jsx: true } },
    sourceType: "module",
  },
});

const tsxRuleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
    sourceType: "module",
  },
});

const literal = (attr, text) => ({
  messageId: "literalName",
  data: { attr, text: JSON.stringify(text) },
});

jsxRuleTester.run("no-literal-accessible-name", rule, {
  valid: [
    // Names from the message layer, props and variables.
    { code: '<button aria-label={t("close")} />' },
    { code: "<img alt={t('avatar_of', { name })} src={src} />" },
    { code: "<input placeholder={placeholder} />" },
    { code: '<Dialog title={t("delete_space")} />' },
    // Decorative images are marked with an empty alt.
    { code: '<img alt="" src={src} />' },
    { code: '<img alt={""} src={src} />' },
    { code: "<img alt={``} src={src} />" },
    // Template literals whose literal parts are only separators.
    { code: '<span title={`${t("file")}: ${name}`} />' },
    { code: "<span aria-label={`${count} / ${total}`} />" },
    // Conditionals and fallbacks built from translated strings.
    { code: '<button aria-label={open ? t("close") : t("open")} />' },
    { code: '<button aria-label={label ?? t("untitled")} />' },
    // Attributes that are not accessible names are out of scope.
    { code: '<div className="title" id="title" data-title="x" />' },
    { code: '<div aria-labelledby="dialog-title" aria-describedby="hint" />' },
    { code: '<Field label="E-post" />' },
    // Valueless and non-string attributes.
    { code: "<input placeholder />" },
    { code: "<div aria-valuetext={42} />" },
  ],
  invalid: [
    {
      code: '<button aria-label="Stäng" />',
      errors: [literal("aria-label", "Stäng")],
    },
    {
      code: '<button aria-label={"Close"} />',
      errors: [literal("aria-label", "Close")],
    },
    // No "has letters" escape: a symbol is not an accessible name.
    {
      code: '<button aria-label="×" />',
      errors: [literal("aria-label", "×")],
    },
    // Empty values other than alt="" are not valid names either.
    {
      code: '<button aria-label="" />',
      errors: [literal("aria-label", "")],
    },
    {
      code: '<img alt=" " src={src} />',
      errors: [literal("alt", "")],
    },
    {
      code: '<img alt="Profilbild" src={src} />',
      errors: [literal("alt", "Profilbild")],
    },
    {
      code: '<input placeholder="Sök" />',
      errors: [literal("placeholder", "Sök")],
    },
    {
      code: '<abbr title="Application Programming Interface">API</abbr>',
      errors: [literal("title", "Application Programming Interface")],
    },
    {
      code: '<PageHeader title="Inställningar" />',
      errors: [literal("title", "Inställningar")],
    },
    {
      code: '<div role="slider" aria-valuetext="Hälften" />',
      errors: [literal("aria-valuetext", "Hälften")],
    },
    {
      code: '<section aria-roledescription="karusell" />',
      errors: [literal("aria-roledescription", "karusell")],
    },
    {
      code: '<div aria-description="Tryck på Enter" />',
      errors: [literal("aria-description", "Tryck på Enter")],
    },
    {
      code: '<div role="textbox" aria-placeholder="Skriv här" />',
      errors: [literal("aria-placeholder", "Skriv här")],
    },
    // Static template literals.
    {
      code: "<button aria-label={`Stäng`} />",
      errors: [literal("aria-label", "Stäng")],
    },
    // Untranslated words around interpolated values.
    {
      code: "<button aria-label={`Ta bort ${name}`} />",
      errors: [literal("aria-label", "Ta bort ${…}")],
    },
    // Every literal branch is reported.
    {
      code: '<button aria-label={open ? "Stäng" : "Öppna"} />',
      errors: [literal("aria-label", "Stäng"), literal("aria-label", "Öppna")],
    },
    {
      code: '<button aria-label={open ? t("close") : "Öppna"} />',
      errors: [literal("aria-label", "Öppna")],
    },
    {
      code: '<button aria-label={label ?? "Namnlös"} />',
      errors: [literal("aria-label", "Namnlös")],
    },
    {
      code: '<img alt={name || "Bild"} src={src} />',
      errors: [literal("alt", "Bild")],
    },
  ],
});

tsxRuleTester.run("no-literal-accessible-name (TypeScript)", rule, {
  valid: [
    { code: '<button aria-label={t("close") as string} />' },
    { code: '<img alt={"" as string} src={src} />' },
  ],
  invalid: [
    {
      code: '<button aria-label={"Stäng" as string} />',
      errors: [literal("aria-label", "Stäng")],
    },
    {
      code: '<button aria-label={("Stäng" satisfies string)} />',
      errors: [literal("aria-label", "Stäng")],
    },
    {
      code: '<input placeholder={value ? undefined : ("Sök" as const)} />',
      errors: [literal("placeholder", "Sök")],
    },
  ],
});
