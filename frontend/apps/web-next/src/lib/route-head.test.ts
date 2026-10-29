import { createTranslator } from "use-intl";
import { expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { rootHead, routeTitle } from "./route-head";

const t = createTranslator({ locale: "sv", messages });

it("titles a route with its message and the app name", () => {
  expect(routeTitle("login")({ match: { context: { t } } })).toEqual({
    meta: [{ title: "Logga in · Eneo" }]
  });
});

it("titles a route without a title of its own with the app name", () => {
  expect(rootHead()).toEqual({ meta: [{ title: "Eneo" }] });
});
