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
  #queuedFiles = new Set<string>();

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

  #cached(fileId: string, kind: "primary" | "original") {
    if (!browser || !fileId) return;
    const key = `${kind}:${fileId}`;
    const record = this.#attachmentUrls.get(key);
    if (record) {
      if (Date.now() < record.expiresAt) {
        return record.url;
      }
    }
    if (!this.#queuedFiles.has(key)) {
      this.#queuedFiles.add(key);
      this.#generateUrl(fileId, kind, key);
    }

    return undefined;
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
    } catch {
      // Left uncached: the next lookup asks again instead of blocking the file.
    } finally {
      this.#queuedFiles.delete(key);
    }
  }
}

export const [getAttachmentUrlService, initAttachmentUrlService] = createClassContext(
  "Attachment URL Service",
  AttachmentUrlService
);
