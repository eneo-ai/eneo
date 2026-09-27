// Chrome's first WebM bytes and a Duration reader, for tests of the recorded files'
// headers (ported from the Tal till text module's tests).

export const hex = (text: string) =>
  Uint8Array.from(text.match(/../g) ?? [], (byte) => parseInt(byte, 16));

// The first bytes Chrome 153's MediaRecorder wrote for audio/webm;codecs=opus,
// mono, 32 kbit/s: the EBML header, a Segment of unknown size, Info
// (TimecodeScale 1 ms, MuxingApp and WritingApp "Chrome", no Duration) and
// Tracks, then the start of the first Cluster.
export const EBML_HEADER = "1a45dfa39f4286810142f7810142f2810442f381084282847765626d42878104428581";
export const SEGMENT_UNKNOWN_SIZE = "021853806701ffffffffffffff";
export const CHROME_INFO = "1549a966992ad7b1830f42404d80864368726f6d655741864368726f6d65";
export const CHROME_TRACKS =
  "1654ae6bbfaebdd7810173c587a04f6d0808643a8381028686415f4f50555363a2934f707573486561640101000080bb0000000000e18db584473b80009f810162648120";
export const CLUSTER_START = "1f43b67501ffffffffffffffe78100a38c81000080fb03ff";
export const chromeWebm = () =>
  hex(EBML_HEADER + SEGMENT_UNKNOWN_SIZE + CHROME_INFO + CHROME_TRACKS + CLUSTER_START);

/** One EBML element with a one-byte size (data under 127 bytes). */
export const element = (id: string, data: string) =>
  id + (0x80 | (data.length / 2)).toString(16).padStart(2, "0") + data;

/**
 * Reads Segment > Info the way a player does, independently of the code under
 * test: the Duration in milliseconds, or null when the file has none.
 */
export function readDurationMs(bytes: Uint8Array): number | null {
  const width = (first: number) => Math.clz32(first) - 23;
  const at = (start: number) => {
    const idWidth = width(bytes[start]);
    const sizeWidth = width(bytes[start + idWidth]);
    const sizeBytes = [...bytes.subarray(start + idWidth, start + idWidth + sizeWidth)];
    const unknown =
      sizeBytes[0] === 0xff >> (sizeWidth - 1) && sizeBytes.slice(1).every((b) => b === 0xff);
    return {
      id: [...bytes.subarray(start, start + idWidth)].reduce((n, b) => n * 256 + b, 0),
      data: start + idWidth + sizeWidth,
      size: unknown
        ? Infinity
        : sizeBytes.reduce((n, b, i) => n * 256 + (i === 0 ? b & (0xff >> sizeWidth) : b), 0)
    };
  };
  const header = at(0);
  const segment = at(header.data + header.size);
  if (segment.id !== 0x18538067) return null;
  for (let child = at(segment.data); child.id !== 0x1f43b675; child = at(child.data + child.size)) {
    if (child.id !== 0x1549a966) continue;
    let scale = 1_000_000;
    let duration: number | null = null;
    for (
      let field = at(child.data);
      field.data < child.data + child.size;
      field = at(field.data + field.size)
    ) {
      const view = new DataView(bytes.buffer, bytes.byteOffset + field.data, field.size);
      if (field.id === 0x2ad7b1)
        scale = [...bytes.subarray(field.data, field.data + field.size)].reduce(
          (n, b) => n * 256 + b,
          0
        );
      if (field.id === 0x4489)
        duration = field.size === 8 ? view.getFloat64(0) : view.getFloat32(0);
    }
    return duration === null ? null : (duration * scale) / 1_000_000;
  }
  return null;
}
