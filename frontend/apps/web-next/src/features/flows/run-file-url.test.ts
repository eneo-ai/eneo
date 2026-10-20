import createClient from "openapi-fetch";
import { describe, expect, it } from "vitest";
import type { paths } from "@/lib/api/schema";
import { signedRunFileUrl } from "./run-file-url";

function clientExpecting(expectedPath: string, url: string) {
  return createClient<paths>({
    baseUrl: "https://beta.example.test/api/eneo",
    fetch: async (request) => {
      expect(request.url).toBe(`https://beta.example.test/api/eneo${expectedPath}`);
      expect(request.method).toBe("POST");
      expect(await request.json()).toEqual({ expires_in: 3600, content_disposition: "attachment" });
      return Response.json({ url, expires_at: 1234 });
    }
  });
}

describe("signed run file URLs", () => {
  it("mints an output through the run's artifact endpoint", async () => {
    const api = clientExpecting(
      "/api/v1/flows/flow-1/runs/run-1/artifacts/file-1/signed-url/",
      "http://backend:8000/api/v1/files/file-1/original/download/?token=signed%2Bvalue"
    );
    expect(await signedRunFileUrl(api, "flow-1", "run-1", { id: "file-1", role: "output" })).toBe(
      "/api/eneo/api/v1/files/file-1/original/download/?token=signed%2Bvalue"
    );
  });

  it("mints an input through the run's input-file endpoint", async () => {
    const api = clientExpecting(
      "/api/v1/flows/flow-1/runs/run-1/input-files/file-2/signed-url/",
      "http://backend:8000/api/v1/files/file-2/original/download/?token=t"
    );
    expect(await signedRunFileUrl(api, "flow-1", "run-1", { id: "file-2", role: "input" })).toBe(
      "/api/eneo/api/v1/files/file-2/original/download/?token=t"
    );
  });

  it.each([
    "http://backend:8000/api/v1/files/other/original/download/?token=value",
    "http://backend:8000/api/v1/files/file-1/download/?token=value",
    "http://backend:8000/api/v1/files/file-1/original/download/"
  ])("rejects an unexpected file capability: %s", async (url) => {
    const api = clientExpecting(
      "/api/v1/flows/flow-1/runs/run-1/artifacts/file-1/signed-url/",
      url
    );
    await expect(
      signedRunFileUrl(api, "flow-1", "run-1", { id: "file-1", role: "output" })
    ).rejects.toThrow("Unexpected signed file URL");
  });
});
