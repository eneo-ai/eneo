/**
 * Decompression-bomb guard for OOXML containers (DOCX/XLSX are zips).
 * mammoth and ExcelJS inflate the whole archive in memory with no ratio
 * check, so a kilobytes-sized bomb declaring gigabytes of XML would OOM the
 * file-ingest worker. This reads only the zip's **central directory** —
 * the declared uncompressed sizes — without inflating anything, and rejects
 * archives whose declared expansion is implausible for a document.
 *
 * The declared sizes are attacker-controlled too, but lying doesn't help:
 * understating makes the real inflate fail in the parser (sizes disagree),
 * and overstating trips this guard.
 */

/** Total declared uncompressed bytes may not exceed max(floor, ratio × packed). */
const MIN_ALLOWED_UNCOMPRESSED_BYTES = 64 * 1024 * 1024;
const MAX_COMPRESSION_RATIO = 100;
/** OOXML archives hold dozens of parts; thousands signal something synthetic. */
const MAX_ZIP_ENTRIES = 10_000;

const EOCD_SIGNATURE = 0x06054b50;
const CDFH_SIGNATURE = 0x02014b50;
/** Fixed EOCD size; the record may be followed by a comment up to 64 KiB. */
const EOCD_SIZE = 22;
const CDFH_SIZE = 46;

export class ZipBombError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZipBombError";
  }
}

function findEocdOffset(buf: Buffer): number | null {
  const scanFloor = Math.max(0, buf.length - EOCD_SIZE - 65_535);
  for (let i = buf.length - EOCD_SIZE; i >= scanFloor; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIGNATURE) return i;
  }
  return null;
}

/**
 * Throws {@link ZipBombError} when the archive's central directory declares
 * an expansion no real document produces. A buffer that isn't a readable zip
 * at all passes — the downstream parser produces the proper format error.
 */
export function assertZipWithinBounds(bytes: Buffer, maxExpandedBytes = 64 * 1024 * 1024): void {
  const eocd = findEocdOffset(bytes);
  if (eocd === null) return;

  const entryCount = bytes.readUInt16LE(eocd + 10);
  const cdOffset = bytes.readUInt32LE(eocd + 16);
  if (entryCount > MAX_ZIP_ENTRIES) {
    throw new ZipBombError(`archive declares ${entryCount} entries (max ${MAX_ZIP_ENTRIES})`);
  }
  // 0xFFFFFFFF marks ZIP64. No legitimate upload under MAX_UPLOAD_BYTES needs
  // a 4 GB+ directory, so treat it as out of bounds rather than parsing the
  // ZIP64 locator.
  if (cdOffset === 0xffffffff || entryCount === 0xffff) {
    throw new ZipBombError("ZIP64 archives are not accepted");
  }

  let totalUncompressed = 0;
  let offset = cdOffset;
  for (let i = 0; i < entryCount; i++) {
    if (offset + CDFH_SIZE > bytes.length || bytes.readUInt32LE(offset) !== CDFH_SIGNATURE) {
      // Truncated/garbled directory — let the real parser report it.
      return;
    }
    const uncompressedSize = bytes.readUInt32LE(offset + 24);
    if (uncompressedSize === 0xffffffff) {
      throw new ZipBombError("ZIP64 entry sizes are not accepted");
    }
    totalUncompressed += uncompressedSize;
    const nameLen = bytes.readUInt16LE(offset + 28);
    const extraLen = bytes.readUInt16LE(offset + 30);
    const commentLen = bytes.readUInt16LE(offset + 32);
    offset += CDFH_SIZE + nameLen + extraLen + commentLen;
  }

  const allowed = Math.min(
    maxExpandedBytes,
    Math.max(MIN_ALLOWED_UNCOMPRESSED_BYTES, bytes.length * MAX_COMPRESSION_RATIO),
  );
  if (totalUncompressed > allowed) {
    throw new ZipBombError(
      `archive declares ${totalUncompressed} uncompressed bytes from ${bytes.length} packed — over the ${allowed}-byte ceiling`,
    );
  }
}
