// @vitest-environment jsdom
import createClient from "openapi-fetch";
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "@/lib/api/base";
import { EneoApiError } from "@/lib/api/errors";
import type { paths } from "@/lib/api/schema";
import {
  proxiedDownloadPath,
  saveBlob,
  saveUrl,
  signedFileUrl,
  toastDownloadError
} from "./signed-file-url";

const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  toast.error.mockClear();
});

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
        `${API_BASE}/api/v1/files/file-1/download/?token=signed%2Bvalue`
      );
    }
  );

  it.each([
    ["download", "/api/v1/files/file-1/download/"],
    ["original", "/api/v1/files/file-1/original/download/"],
    ["info-blob-original", "/api/v1/info-blobs/file-1/original/download/"]
  ] as const)("keeps only the %s path and its token, never the signing host", (kind, path) => {
    expect(proxiedDownloadPath(`http://backend:8000${path}?token=t`, "file-1", kind)).toBe(
      `${API_BASE}${path}?token=t`
    );
  });

  it.each([
    ["download", "http://backend:8000/api/v1/files/file-1/original/download/?token=t"],
    ["download", "http://backend:8000/api/v1/files/other/download/?token=t"],
    ["download", "http://backend:8000/api/v1/files/file-1/download/"],
    ["download", "http://evil.example/steal?token=t"],
    ["original", "http://backend:8000/api/v1/files/file-1/download/?token=t"],
    ["original", "http://backend:8000/api/v1/files/other/original/download/?token=t"],
    ["original", "http://backend:8000/api/v1/files/file-1/original/download/?token="],
    ["original", "http://evil.example/steal?token=t"],
    ["info-blob-original", "http://backend:8000/api/v1/files/file-1/original/download/?token=t"],
    [
      "info-blob-original",
      "http://backend:8000/api/v1/info-blobs/other/original/download/?token=t"
    ],
    [
      "info-blob-original",
      "http://backend:8000/api/v1/info-blobs/file-1/original/download/?token="
    ],
    ["info-blob-original", "http://evil.example/steal?token=t"]
  ] as const)("refuses for the %s kind: %s", (kind, url) => {
    expect(() => proxiedDownloadPath(url, "file-1", kind)).toThrow("Unexpected signed file URL");
  });

  it("proxiedDownloadPath prefixes API_BASE", () => {
    expect(
      proxiedDownloadPath("http://backend:8000/api/v1/files/file-1/download/?token=t", "file-1")
    ).toBe(`${API_BASE}/api/v1/files/file-1/download/?token=t`);
  });

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

describe("toastDownloadError", () => {
  const t = (key: string) => key;

  it("says a feature's own refusal with the support references", () => {
    toastDownloadError(new EneoApiError("Gone.", { status: 404, errorId: "err-1" }), t, {
      message: "Filen finns inte för den här körningen."
    });
    expect(toast.error).toHaveBeenCalledWith("Filen finns inte för den här körningen.", {
      description: "error_id: err-1"
    });
  });

  it("says the file did not load when no backend answer explains why", () => {
    toastDownloadError(new Error("Unexpected signed file URL"), t, { message: "Ignored." });
    expect(toast.error).toHaveBeenCalledWith("attachment_error_loading_content");
  });
});

describe("saving a file", () => {
  it("clicks a detached-after-use anchor that names the file and sends no referrer", () => {
    let connected = false;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => (connected = document.querySelector("a[download]") !== null));

    saveUrl("/api/eneo/api/v1/files/file-1/download/?token=t", "rapport.pdf");

    expect(click).toHaveBeenCalledTimes(1);
    expect(connected).toBe(true);
    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.getAttribute("href")).toBe("/api/eneo/api/v1/files/file-1/download/?token=t");
    expect(anchor.download).toBe("rapport.pdf");
    expect(anchor.rel).toBe("noreferrer");
    expect(anchor.isConnected).toBe(false);
  });

  it("saves a blob through an object URL it revokes after the browser has read it", () => {
    vi.useFakeTimers();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const revoke = vi.fn();
    const previous = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    Object.assign(URL, { createObjectURL: () => "blob:local/1", revokeObjectURL: revoke });
    try {
      saveBlob(new Blob(["Hej"]), "svar.txt");

      expect(click).toHaveBeenCalledTimes(1);
      expect(revoke).not.toHaveBeenCalled();
      vi.advanceTimersByTime(10_000);
      expect(revoke).toHaveBeenCalledWith("blob:local/1");
    } finally {
      Object.assign(URL, { createObjectURL: previous.create, revokeObjectURL: previous.revoke });
    }
  });
});
