import { createTranslator } from "use-intl";
import { expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { resourceTitle, rootHead, routeTitle, spaceName, spaceTitle, title } from "./route-head";

const t = createTranslator({ locale: "sv", messages });

it("titles a route with its message and the app name", () => {
  expect(routeTitle("login")({ match: { context: { t } } })).toEqual({
    meta: [{ title: "Logga in · Eneo" }]
  });
});

it("titles a route without a title of its own with the app name", () => {
  expect(rootHead()).toEqual({ meta: [{ title: "Eneo" }] });
});

it("joins page and space titles under the app title", () => {
  expect(title("Kunskap", "Upphandling")).toEqual({
    meta: [{ title: "Kunskap · Upphandling · Eneo" }]
  });
  expect(title("Kunskap")).toEqual({ meta: [{ title: "Kunskap · Eneo" }] });
});

it.each([
  [{ name: "Backend name", personal: true, organization: false }, "Personligt"],
  [{ name: "Backend name", personal: false, organization: true }, "Organisation"],
  [{ name: "Upphandling", personal: false, organization: false }, "Upphandling"]
])("localizes space aliases while preserving shared names", (space, expected) => {
  expect(spaceName(space, t)).toBe(expected);
});

it("uses the space layout rather than a nested resource with a name", () => {
  const matches = [
    {
      routeId: "/_app/spaces/$spaceId",
      loaderData: { name: "Backend name", personal: true, organization: false }
    },
    { routeId: "/_app/spaces/$spaceId/assistants/$assistantId", loaderData: { name: "Assistant" } }
  ];
  expect(spaceTitle(matches, t, "Kunskap")).toEqual({
    meta: [{ title: "Kunskap · Personligt · Eneo" }]
  });
  expect(spaceTitle(matches, t)).toEqual({ meta: [{ title: "Personligt · Eneo" }] });
});

it("falls back when the layout or resource has no loader data", () => {
  const matches = [{ routeId: "/_app/spaces/$spaceId", loaderData: undefined }];
  expect(spaceTitle(matches, t)).toEqual({ meta: [{ title: "Eneo" }] });
  expect(spaceTitle([], t, "Kunskap")).toEqual({ meta: [{ title: "Kunskap · Eneo" }] });
  const head = resourceTitle("knowledge");
  expect(head({ matches, match: { context: { t } }, loaderData: undefined })).toEqual({
    meta: [{ title: "Kunskap · Eneo" }]
  });
});
