// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { act, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { renderInApp } from "@/test/render";
import type { Service } from "../services";

const update = vi.hoisted(() => vi.fn());

vi.mock("./use-service", () => ({
  useUpdateService: () => useMutation({ mutationFn: (body: unknown) => update(body) })
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => makeSpace()) };
});

import { ServiceEditor } from "./service-editor";

afterEach(() => {
  cleanup();
  update.mockReset();
});

const service = (json_schema: Service["json_schema"]) =>
  ({
    id: "service-1",
    name: "Sammanfattning",
    prompt: "Sammanfatta texten.",
    completion_model: null,
    completion_model_kwargs: {},
    output_format: "json",
    json_schema
  }) as unknown as Service;

it("treats a saved JSON schema as saved, whatever its formatting", async () => {
  update.mockResolvedValue({});
  const { rerender, unmount } = renderInApp(<ServiceEditor service={service(null)} />);
  const schema = () => document.getElementById("service-json-schema") as HTMLTextAreaElement;

  fireEvent.change(schema(), { target: { value: '{"type":"object"}' } });
  fireEvent.blur(schema());
  await waitFor(() =>
    expect(update).toHaveBeenCalledWith({ output_format: "json", json_schema: { type: "object" } })
  );

  // The server answers with the parsed schema, which renders pretty-printed.
  rerender(<ServiceEditor service={service({ type: "object" })} />);
  fireEvent.blur(schema());
  unmount();
  await act(async () => {});

  expect(update).toHaveBeenCalledTimes(1);
});
