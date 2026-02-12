import { browser } from "$app/environment";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { getIntric } from "$lib/core/Intric";
import type { Intric } from "@intric/intric-js";
import { SvelteMap } from "svelte/reactivity";

const EXPIRES_AFTER_SECONDS = 3600;

/** We cache generated Attachment URLs to not constantly regenerate them */
class AttachmentUrlService {
  #intric: Intric;
  #attachmentUrls = new SvelteMap<string, { url: string | undefined; expiresAt: number }>();
  #queuedFiles = new Set<string>();

  constructor({ intric = getIntric() }: { intric: Intric }) {
    this.#intric = intric;
  }

  /**
   * Returns a sigend URL for the requested file for use inside templates.
   *
   *
   *  */
  getUrl(file: { id: string }) {
    if (!browser || !file.id) return;
    const record = this.#attachmentUrls.get(file.id);
    if (record) {
      if (Date.now() < record.expiresAt) {
        return record.url;
      }
    }
    if (!this.#queuedFiles.has(file.id)) {
      this.#queuedFiles.add(file.id);
      this.#generateUrl(file.id);
    }

    return undefined;
  }

  async #generateUrl(fileId: string) {
    const { url, expires_at } = await this.#intric.files.generateSignedUrl({
      fileId,
      contentDisposition: "attachment",
      expiresIn: EXPIRES_AFTER_SECONDS + 60
    });
    this.#attachmentUrls.set(fileId, { url, expiresAt: expires_at * 1000 });
    this.#queuedFiles.delete(fileId);
  }
}

export const [getAttachmentUrlService, initAttachmentUrlService] = createClassContext(
  "Attachment URL Service",
  AttachmentUrlService
);
