// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { Schema } from "@/lib/api/models";
import { renderInApp } from "@/test/render";
import { WidgetPersonaFields } from "./widget-persona-fields";

type WidgetPersona = Schema<"WidgetPersona">;

const api = vi.hoisted(() => ({ DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const upload = vi.hoisted(() => vi.fn<() => Promise<Response>>());
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  apiFetch: upload
}));

/** An upload that finishes when the test says so. */
function slowUpload(id = "icon-new") {
  let finish!: () => void;
  upload.mockReturnValue(
    new Promise<Response>((resolve) => {
      finish = () => resolve(new Response(JSON.stringify({ id }), { status: 200 }));
    })
  );
  return () => finish();
}

/** The owner of a persona, as the editor is: it keeps what it is handed. */
function Owner({
  initial,
  onChange
}: {
  initial: WidgetPersona;
  onChange: (persona: WidgetPersona) => void;
}) {
  const [persona, setPersona] = useState(initial);
  return (
    <WidgetPersonaFields
      persona={persona}
      assistantIconId="icon-a"
      onChange={(next) => {
        setPersona(next);
        onChange(next);
      }}
    />
  );
}

/** An owner whose persona a template can take over while an upload runs. */
function LockableOwner({
  initial,
  onChange
}: {
  initial: WidgetPersona;
  onChange: (persona: WidgetPersona) => void;
}) {
  const [persona, setPersona] = useState(initial);
  const [locked, setLocked] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setLocked(true)}>
        Koppla mallen
      </button>
      <WidgetPersonaFields
        persona={persona}
        assistantIconId="icon-a"
        locked={locked}
        lockHint="Styrs av mallen"
        onChange={(next) => {
          setPersona(next);
          onChange(next);
        }}
      />
    </>
  );
}

function show(
  initial: WidgetPersona = { name: "Kim", avatar_icon_id: null, avatar_in_launcher: false },
  Component: typeof Owner = Owner
) {
  const onChange = vi.fn<(persona: WidgetPersona) => void>();
  // The assistant's icon, fetched to be uploaded again as the persona's own.
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "image/png" } })
    )
  );
  api.DELETE.mockResolvedValue({});
  const rendered = renderInApp(<Component initial={initial} onChange={onChange} />);
  return { ...rendered, onChange };
}

afterEach(() => {
  vi.unstubAllGlobals();
  api.DELETE.mockReset();
  upload.mockReset();
});

describe("WidgetPersonaFields avatar uploads", () => {
  it("attaches the copied icon to the name typed while it was uploading", async () => {
    const finish = slowUpload();
    const { onChange } = show();
    fireEvent.click(screen.getByRole("button", { name: "Använd assistentens ikon" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), { target: { value: "Kimmy" } });
    expect(onChange).toHaveBeenLastCalledWith({
      name: "Kimmy",
      avatar_icon_id: null,
      avatar_in_launcher: false
    });

    finish();
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith({
        name: "Kimmy",
        avatar_icon_id: "icon-new",
        avatar_in_launcher: false
      })
    );
    expect(api.DELETE).not.toHaveBeenCalled();
  });

  it("lets a copied icon go when the persona was cleared while it was uploading", async () => {
    const finish = slowUpload();
    const { onChange } = show();
    fireEvent.click(screen.getByRole("button", { name: "Använd assistentens ikon" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), { target: { value: "" } });
    const cleared = { name: "", avatar_icon_id: null, avatar_in_launcher: false };
    expect(onChange).toHaveBeenLastCalledWith(cleared);

    finish();
    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/icons/{id}/", {
        params: { path: { id: "icon-new" } }
      })
    );
    expect(onChange).toHaveBeenLastCalledWith(cleared);
    expect(screen.getByText("Ge personan ett namn innan du väljer avatar.")).toBeTruthy();
  });

  it("lets a copied icon go when a template took the persona over while it was uploading", async () => {
    const finish = slowUpload();
    const { onChange } = show(undefined, LockableOwner);
    fireEvent.click(screen.getByRole("button", { name: "Använd assistentens ikon" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Koppla mallen" }));
    expect(screen.getAllByText("Styrs av mallen").length).toBeGreaterThan(0);

    finish();
    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/icons/{id}/", {
        params: { path: { id: "icon-new" } }
      })
    );
    // A locked persona cannot change: no avatar is attached to it.
    expect(onChange).not.toHaveBeenCalled();
  });

  it("attaches an uploaded file to the name typed while it was uploading", async () => {
    const finish = slowUpload();
    const { container, onChange } = show();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "icon.png", { type: "image/png" })] }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), { target: { value: "Kimmy" } });

    finish();
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith({
        name: "Kimmy",
        avatar_icon_id: "icon-new",
        avatar_in_launcher: false
      })
    );
  });
});
