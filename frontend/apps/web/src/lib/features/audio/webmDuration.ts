/**
 * Chrome's MediaRecorder writes WebM without a Duration, so a player cannot
 * tell the length: Chrome's own reports Infinity and its timeline jumps back
 * as it re-estimates. This writes the recorded duration into Segment > Info
 * of a file's first bytes, which hold the whole header, and leaves the audio
 * after it alone. It keeps the file's TimecodeScale. Anything it does not
 * recognise gives null, and the caller keeps the bytes as they were: so does
 * a header cut off before its Info ends, since one chunk need not hold it all.
 *
 * Not the fix-webm-duration package: that reads and rewrites the whole file
 * (a 5-hour part is about 72 MB), runs only in a browser (FileReader), and
 * resets TimecodeScale to 1 ms, which would misplace clusters written with
 * another scale.
 */

import { withinTime } from "./withinTime";

const EBML_HEADER = 0x1a45dfa3;
const SEGMENT = 0x18538067;
const SEEK_HEAD = 0x114d9b74;
const INFO = 0x1549a966;
const TIMECODE_SCALE = 0x2ad7b1;
const DURATION = 0x4489;
// A checksum over its parent's other children: a patch would break it.
const CRC_32 = 0xbf;
const DEFAULT_TIMECODE_SCALE_NS = 1_000_000;

interface Element {
  id: number;
  sizeStart: number;
  sizeLength: number;
  dataStart: number;
  /** null: unknown size, the element runs to the end of its parent. */
  size: number | null;
}

/** An EBML variable-length field's length: the leading zeros of its first byte, plus one. */
function fieldLength(first: number | undefined): number {
  return first ? Math.clz32(first) - 23 : 0;
}

/** The element at `start`, whole before `end` unless its size is unknown; null when cut off or malformed. */
function readElement(bytes: Uint8Array, start: number, end = bytes.length): Element | null {
  const idLength = fieldLength(bytes[start]);
  const sizeStart = start + idLength;
  const sizeLength = fieldLength(bytes[sizeStart]);
  const dataStart = sizeStart + sizeLength;
  if (idLength < 1 || sizeLength < 1 || dataStart > bytes.length) return null;
  let id = 0;
  for (let i = start; i < sizeStart; i++) id = id * 256 + bytes[i];
  let size = bytes[sizeStart] & (0xff >> sizeLength);
  let unknown = size === 0xff >> sizeLength;
  for (let i = sizeStart + 1; i < dataStart; i++) {
    size = size * 256 + bytes[i];
    unknown &&= bytes[i] === 0xff;
  }
  if (!unknown && dataStart + size > end) return null;
  return { id, sizeStart, sizeLength, dataStart, size: unknown ? null : size };
}

/** A size field for `value`, at least `minLength` bytes (all ones would mean "unknown"). */
function sizeField(value: number, minLength: number): Uint8Array {
  let length = minLength;
  while (value >= 2 ** (7 * length) - 1) length += 1;
  const field = new Uint8Array(length);
  for (let i = length - 1, rest = value; i >= 0; i--, rest = Math.floor(rest / 256)) {
    field[i] = rest % 256;
  }
  field[0] |= 0x80 >> (length - 1);
  return field;
}

export function withWebmDuration(
  bytes: Uint8Array,
  durationMs: number
): Uint8Array<ArrayBuffer> | null {
  const header = readElement(bytes, 0);
  if (header?.id !== EBML_HEADER || header.size === null) return null;
  // The Segment runs on past these first bytes; only its own id and size need to be here.
  const segment = readElement(bytes, header.dataStart + header.size, Infinity);
  if (segment?.id !== SEGMENT) return null;

  // Info comes before the first Cluster, whose size a recorder leaves unknown.
  let info: (Element & { size: number }) | null = null;
  let seekHead = false;
  for (let at = segment.dataStart; !info;) {
    const child = readElement(bytes, at);
    if (!child || child.size === null || child.id === CRC_32) return null;
    if (child.id === INFO) info = { ...child, size: child.size };
    seekHead ||= child.id === SEEK_HEAD;
    at = child.dataStart + child.size;
  }
  const infoEnd = info.dataStart + info.size;

  let scale = DEFAULT_TIMECODE_SCALE_NS;
  let duration: Element | null = null;
  for (let at = info.dataStart; at < infoEnd;) {
    const child = readElement(bytes, at, infoEnd);
    if (!child || child.size === null || child.id === CRC_32) return null;
    if (child.id === TIMECODE_SCALE) {
      scale = 0;
      for (let i = child.dataStart; i < child.dataStart + child.size; i++)
        scale = scale * 256 + bytes[i];
      // A player reads an unsigned integer of at most 8 bytes, and a scale of 0 means nothing.
      if (child.size > 8 || scale === 0) return null;
    }
    if (child.id === DURATION) duration = child;
    at = child.dataStart + child.size;
  }
  const ticks = (durationMs * 1_000_000) / scale;

  if (duration) {
    if (duration.size !== 4 && duration.size !== 8) return null;
    const patched = bytes.slice();
    const view = new DataView(patched.buffer);
    if (duration.size === 8) view.setFloat64(duration.dataStart, ticks);
    else view.setFloat32(duration.dataStart, ticks);
    return patched;
  }
  // Adding a Duration moves the bytes after it, which a SeekHead points at.
  if (seekHead) return null;

  const added = new Uint8Array(11);
  added.set([0x44, 0x89, 0x88]); // Duration, 8 bytes
  new DataView(added.buffer).setFloat64(3, ticks);
  const infoSize = sizeField(info.size + added.length, info.sizeLength);
  const growth = added.length + infoSize.length - info.sizeLength;
  const segmentSize =
    segment.size === null
      ? bytes.subarray(segment.sizeStart, segment.dataStart)
      : sizeField(segment.size + growth, segment.sizeLength);
  const pieces = [
    bytes.subarray(0, segment.sizeStart),
    segmentSize,
    bytes.subarray(segment.dataStart, info.sizeStart),
    infoSize,
    bytes.subarray(info.dataStart, infoEnd),
    added,
    bytes.subarray(infoEnd)
  ];
  const patched = new Uint8Array(pieces.reduce((sum, piece) => sum + piece.length, 0));
  let offset = 0;
  for (const piece of pieces) {
    patched.set(piece, offset);
    offset += piece.length;
  }
  return patched;
}

// Info comes before the first Cluster, a few hundred bytes into a recorder's file:
// only this much of a part's first chunk is read and copied, and not for long.
const HEADER_BYTES = 16 * 1024;
const HEADER_READ_MS = 2_000;

// A WebM part's first chunk holds its header: that chunk with the recorded duration
// written in, or as it was (not WebM, a header this does not recognise, or bytes
// that did not come in time).
export async function withRecordedDuration(
  firstChunk: Blob,
  durationMs: number,
  mimeType: string = firstChunk.type
): Promise<Blob> {
  if (!/^(audio|video)\/webm\b/i.test(mimeType)) return firstChunk;
  const head = firstChunk.slice(0, HEADER_BYTES);
  const bytes = await withinTime(
    head
      .arrayBuffer()
      .then((buffer) => new Uint8Array(buffer))
      .catch(() => null),
    HEADER_READ_MS,
    null
  );
  const patched = bytes && withWebmDuration(bytes, durationMs);
  return patched
    ? new Blob([patched, firstChunk.slice(head.size)], { type: firstChunk.type })
    : firstChunk;
}
