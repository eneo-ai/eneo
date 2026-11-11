import { createTranslator } from "use-intl";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";

type Catalog = Record<string, string>;

/**
 * A translator over the app's real catalog for `locale`, or over `messages`.
 * Tests use this instead of `createTranslator`: handed a catalog literal,
 * use-intl infers every key and ICU argument of it, which costs minutes of
 * type checking and typed linting. Look keys up in the imported catalog
 * (`messages.key`) to keep typos a type error.
 */
export function testTranslator(
  locale = "sv",
  messages: Catalog = locale === "en" ? en : sv
): ReturnType<typeof createTranslator> {
  return createTranslator({ locale, messages });
}
