import createClient from "openapi-fetch";
import { describe, expect, it } from "vitest";
import type { paths } from "@/lib/api/schema";
import { signedFileUrl } from "./signed-file-url";

describe("signed file URLs", () => {
  it.each(["inline", "attachment"] as const)(
    "serves %s files through the browser origin even when backend names its internal host",
    async (disposition) => {
      const api = createClient<paths>({
        baseUrl: "https://beta.example.test/api/eneo",
        fetch: async (request) => {
          expect(request.url).toBe(
            "https://beta.example.test/api/eneo/api/v1/files/file-1/signed-url/"
          );
          expect(request.method).toBe("POST");
          expect(await request.json()).toEqual({
            expires_in: 3600,
            content_disposition: disposition
          });
          return Response.json({
            url: "http://backend:8000/api/v1/files/file-1/download/?token=signed%2Bvalue",
            expires_at: 1234
          });
        }
      });
      expect(await signedFileUrl(api, "file-1", disposition)).toBe(
        "/api/eneo/api/v1/files/file-1/download/?token=signed%2Bvalue"
      );
    }
  );

  it.each([
    "http://backend:8000/api/v1/files/other/download/?token=value",
    "http://backend:8000/other?token=value",
    "http://backend:8000/api/v1/files/file-1/download/",
    "http://backend:8000/api/v1/files/file-1/download/?token="
  ])("rejects an unexpected file capability: %s", async (url) => {
    const api = createClient<paths>({
      baseUrl: "https://beta.example.test/api/eneo",
      fetch: async () => Response.json({ url, expires_at: 1234 })
    });
    await expect(signedFileUrl(api, "file-1", "attachment")).rejects.toThrow(
      "Unexpected signed file URL"
    );
  });

  it("propagates authorization failures instead of producing a download URL", async () => {
    const api = createClient<paths>({
      baseUrl: "https://beta.example.test/api/eneo",
      fetch: async () => Response.json({ detail: "Forbidden" }, { status: 403 })
    });
    await expect(signedFileUrl(api, "file-1", "attachment")).rejects.toThrow();
  });
});
