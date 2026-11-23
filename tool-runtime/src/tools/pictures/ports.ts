/** The files pictures are taken out of. */
export const PICTURE_FILE_KINDS = ["pdf", "docx", "pptx"] as const;
export type PictureFileKind = (typeof PICTURE_FILE_KINDS)[number];

/**
 * Child job: cut a window of the pictures out of one downloaded file. `directory` is made
 * by the parent for this call and holds the file as `source`; the pictures are written to
 * its `out` directory.
 */
export type ExtractImagesJob = {
  kind: "extract_images";
  directory: string;
  fileKind: PictureFileKind;
  /** The first picture wanted, counted from 0 in document order, and how many. */
  offset: number;
  limit: number;
  /** For a PDF: only the pictures on this page (1 is the first). */
  page?: number;
  /** PDF pages searched at most. */
  maxPages: number;
};

export type ExtractedPicture = {
  /** File name inside the job's `out` directory. */
  file: string;
  mimeType: "image/png" | "image/jpeg";
  width: number;
  height: number;
  page?: number;
};
/** The window's pictures, and how many the file (or the page asked for) has in all. */
export type ExtractImagesResult = {
  total: number;
  pictures: ExtractedPicture[];
};

export const SOURCE_FILE = "source";
export const OUTPUT_DIRECTORY = "out";
