import { expect, it } from "vitest";
import { makeQueryClient } from "@/lib/api/query";
import { invalidateSpaces, invalidateSpacesList } from "./space";

it("distinguishes the spaces list from details, nested resources and unrelated queries", async () => {
  const client = makeQueryClient();
  const keys = [["spaces"], ["spaces", "space-1"], ["spaces", "space-1", "files"], ["settings"]];
  for (const key of keys) client.setQueryData(key, {});
  const invalidated = () => keys.map((key) => client.getQueryState(key)?.isInvalidated);
  await invalidateSpacesList(client);
  expect(invalidated()).toEqual([true, false, false, false]);
  await invalidateSpaces(client);
  expect(invalidated()).toEqual([true, true, true, false]);
});
