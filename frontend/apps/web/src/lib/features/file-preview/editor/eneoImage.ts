import Image, { type ImageOptions } from "@tiptap/extension-image";
import { fileHandleId } from "$lib/components/markdown/FileImageContext";
import { sanitizeImageSrc } from "$lib/components/markdown/sanitizeUrl";

export type EneoImageOptions = ImageOptions & {
  /** A link the reader may load the file a handle names from; undefined when there is none. */
  resolveImage?: (fileId: string) => Promise<string | undefined>;
};

/**
 * An image in a document. The tools name an image of the conversation by its
 * file handle (`eneo-file:<id>`), which stays in the document as written; the
 * view resolves it to a link. Any other address reaches the page only as
 * http(s) or image data.
 */
export const EneoImage = Image.extend<EneoImageOptions>({
  addOptions() {
    return {
      ...this.parent?.(),
      // Inline, as Markdown has it: an image stands inside its paragraph.
      inline: true,
      allowBase64: false,
      resolveImage: undefined
    } as EneoImageOptions;
  },

  addNodeView() {
    return ({ node }) => {
      const { src, alt, title } = node.attrs as {
        src: string | null;
        alt: string | null;
        title: string | null;
      };
      const dom = document.createElement("span");
      dom.className = "eneo-figure";
      const image = document.createElement("img");
      image.alt = alt ?? "";
      const fallback = document.createElement("span");
      fallback.className = "eneo-figure-fallback";
      fallback.textContent = alt ?? "";
      const caption = document.createElement("span");
      caption.className = "eneo-figure-caption";
      caption.textContent = title ?? "";

      let mounted = true;
      const show = (url: string | undefined) => {
        if (!mounted) return;
        if (url) image.src = url;
        dom.replaceChildren(url ? image : fallback, ...(title ? [caption] : []));
      };

      const fileId = fileHandleId(src);
      if (fileId) {
        // The alt text stands in until the link has arrived.
        show(undefined);
        this.options.resolveImage?.(fileId).then(show, () => show(undefined));
      } else {
        show(sanitizeImageSrc(src));
      }

      return {
        dom,
        ignoreMutation: () => true,
        update: (updated) => updated.type === node.type && updated.attrs.src === src,
        destroy() {
          mounted = false;
        }
      };
    };
  }
});
