import { browser } from "$app/environment";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { getEneo } from "$lib/core/Eneo";
import type { Eneo } from "@eneo/eneo-js";
import { SvelteMap } from "svelte/reactivity";

const EXPIRES_AFTER_SECONDS = 3600;
// Original-bytes links are capped server-side at one hour.
const ORIGINAL_MAX_EXPIRES_IN_SECONDS = 3600;

/** We cache generated Attachment URLs to not constantly regenerate them */
class AttachmentUrlService {
  #eneo: Eneo;
  #attachmentUrls = new SvelteMap<string, { url: string | undefined; expiresAt: number }>();
  #pending = new Map<string, Promise<string | undefined>>();

  constructor({ eneo = getEneo() }: { eneo: Eneo }) {
    this.#eneo = eneo;
  }

  /**
   * Returns a sigend URL for the requested file for use inside templates.
   *
   *
   *  */
  getUrl(file: { id: string }) {
    return this.#cached(file.id, "primary");
  }

  /**
   * Returns a signed URL for the exact bytes originally stored, never a processed
   * representation. Use it to download documents: for a file of type TEXT (a DOCX, PDF or XLSX
   * a tool created) the primary representation is its extracted text.
   */
  getOriginalUrl(file: { id: string }) {
    return this.#cached(file.id, "original");
  }

  /**
   * Resolves the signed URL for the exact bytes originally stored, for code that
   * needs to read the file rather than link to it. Shares the cache with
   * `getOriginalUrl`; rejects when no link can be minted for the file.
   */
  async resolveOriginalUrl(file: { id: string }): Promise<string> {
    const key = `original:${file.id}`;
    const url = this.#fresh(key) ?? (await this.#request(file.id, "original", key));
    if (!url) throw new Error("No original download link for this file");
    return url;
  }

  #fresh(key: string) {
    const record = this.#attachmentUrls.get(key);
    return record && Date.now() < record.expiresAt ? record.url : undefined;
  }

  #cached(fileId: string, kind: "primary" | "original") {
    if (!browser || !fileId) return;
    const key = `${kind}:${fileId}`;
    const url = this.#fresh(key);
    if (url) return url;
    void this.#request(fileId, kind, key);
    return undefined;
  }

  /** One request per link at a time; concurrent callers share it. */
  #request(fileId: string, kind: "primary" | "original", key: string) {
    let pending = this.#pending.get(key);
    if (!pending) {
      pending = this.#generateUrl(fileId, kind, key);
      this.#pending.set(key, pending);
    }
    return pending;
  }

  async #generateUrl(fileId: string, kind: "primary" | "original", key: string) {
    try {
      const { url, expires_at } =
        kind === "original"
          ? await this.#eneo.files.generateOriginalSignedUrl({
              fileId,
              contentDisposition: "attachment",
              expiresIn: ORIGINAL_MAX_EXPIRES_IN_SECONDS
            })
          : await this.#eneo.files.generateSignedUrl({
              fileId,
              contentDisposition: "attachment",
              expiresIn: EXPIRES_AFTER_SECONDS + 60
            });
      this.#attachmentUrls.set(key, { url, expiresAt: expires_at * 1000 });
      return url;
    } catch {
      // Left uncached: the next lookup asks again instead of blocking the file.
      return undefined;
    } finally {
      this.#pending.delete(key);
    }
  }
}

export const [getAttachmentUrlService, initAttachmentUrlService] = createClassContext(
  "Attachment URL Service",
  AttachmentUrlService
);
