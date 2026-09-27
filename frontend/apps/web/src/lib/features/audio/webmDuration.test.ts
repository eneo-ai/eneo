import { afterEach, describe, expect, it, vi } from "vitest";

import { withRecordedDuration, withWebmDuration } from "./webmDuration";
import {
  chromeWebm,
  CHROME_INFO,
  CHROME_TRACKS,
  CLUSTER_START,
  EBML_HEADER,
  element,
  hex,
  readDurationMs,
  SEGMENT_UNKNOWN_SIZE
} from "./webmDurationTestFixtures";

describe("withWebmDuration", () => {
  it("writes the recorded duration into Chrome's header and leaves the audio after it alone", () => {
    const original = chromeWebm();
    // Chrome writes no Duration.
    expect(readDurationMs(original)).toBeNull();

    const patched = withWebmDuration(original, 5_000)!;
    expect(readDurationMs(patched)).toBe(5_000);
    // The Segment keeps its unknown size.
    const untilInfo = hex(EBML_HEADER + SEGMENT_UNKNOWN_SIZE);
    expect(patched.subarray(0, untilInfo.length)).toEqual(untilInfo);
    const audio = hex(CHROME_TRACKS + CLUSTER_START);
    expect(patched.subarray(patched.length - audio.length)).toEqual(audio);
    expect(readDurationMs(withWebmDuration(original, 2 * 60 * 60 * 1_000)!)).toBe(7_200_000);
  });

  it("replaces an existing Duration in place, in the file's own time scale", () => {
    const microsecondTicks = element("2ad7b1", "0186a0"); // TimecodeScale 100 000 ns
    for (const zero of ["0000000000000000", "00000000"]) {
      const original = hex(
        EBML_HEADER +
          SEGMENT_UNKNOWN_SIZE +
          element("1549a966", microsecondTicks + element("4489", zero)) +
          CLUSTER_START
      );
      const patched = withWebmDuration(original, 5_000)!;
      expect(patched.length).toBe(original.length);
      expect(readDurationMs(patched)).toBe(5_000);
      const at = patched.length - hex(CLUSTER_START).length - zero.length / 2;
      const view = new DataView(patched.buffer);
      // 5 s in 100 µs ticks.
      expect(zero.length === 16 ? view.getFloat64(at) : view.getFloat32(at)).toBe(50_000);
    }
  });

  it("grows a Segment of known size with its Info, also in a part's first chunk", () => {
    const body = hex(CHROME_INFO + CHROME_TRACKS + CLUSTER_START);
    const size = "01" + body.length.toString(16).padStart(14, "0");
    const original = hex(
      EBML_HEADER + "02" + "18538067" + size + CHROME_INFO + CHROME_TRACKS + CLUSTER_START
    );
    const patched = withWebmDuration(original, 1_500)!;
    expect(readDurationMs(patched)).toBe(1_500);
    const segmentData = EBML_HEADER.length / 2 + 1 + 4 + 8;
    const view = new DataView(patched.buffer);
    const segmentSize = Number(view.getBigUint64(segmentData - 8) & 0x00ffffffffffffffn);
    expect(segmentSize).toBe(patched.length - segmentData);

    // A part's first chunk holds only the start of its Segment.
    const firstChunk = original.subarray(0, original.length - hex(CLUSTER_START).length);
    expect(readDurationMs(withWebmDuration(firstChunk, 1_500)!)).toBe(1_500);
  });

  it("gives null for files it does not recognise", () => {
    const seekHeadFirst = hex(
      EBML_HEADER +
        SEGMENT_UNKNOWN_SIZE +
        element("114d9b74", "4dbb8b53ab841549a96653ac8100") +
        CHROME_INFO +
        CLUSTER_START
    );
    // A SeekHead would point past moved bytes.
    expect(withWebmDuration(seekHeadFirst, 1_000)).toBeNull();
    expect(withWebmDuration(hex("0000001c6674797069736f6d"), 1_000)).toBeNull(); // MP4
    expect(withWebmDuration(chromeWebm().subarray(0, 60), 1_000)).toBeNull(); // cut off in Info
    expect(withWebmDuration(new Uint8Array(), 1_000)).toBeNull();
  });

  it("patches every prefix of Chrome's first bytes once its whole Info is there, and never throws", () => {
    const whole = chromeWebm();
    const infoEnd = hex(EBML_HEADER + SEGMENT_UNKNOWN_SIZE + CHROME_INFO).length;
    for (let length = 0; length <= whole.length; length += 1) {
      const prefix = whole.subarray(0, length);
      const patched = withWebmDuration(prefix, 5_000);
      if (length < infoEnd) {
        expect(patched, `cut off at byte ${length}`).toBeNull();
        continue;
      }
      expect(readDurationMs(patched!), `at byte ${length}`).toBe(5_000);
      expect(patched!.subarray(patched!.length - (length - infoEnd))).toEqual(
        prefix.subarray(infoEnd)
      );
    }
  });

  it("gives null for fields that run past their Info, or that no player could read", () => {
    const info = (fields: string) =>
      hex(EBML_HEADER + SEGMENT_UNKNOWN_SIZE + element("1549a966", fields));
    const cases: Array<[string, Uint8Array]> = [
      [
        "a Duration longer than its Info",
        hex(
          EBML_HEADER +
            SEGMENT_UNKNOWN_SIZE +
            element("1549a966", element("2ad7b1", "0f4240") + "448988" + "00000000") +
            CLUSTER_START
        )
      ],
      [
        "a TimecodeScale of nine bytes",
        info(element("2ad7b1", "000000000000000f42") + element("4489", "00000000"))
      ],
      ["a TimecodeScale of zero", info(element("2ad7b1", "00"))],
      ["a field longer than the file", info(element("2ad7b1", "0f4240") + "4d8001ffffffffffff00")],
      ["an Info size cut in half", hex(EBML_HEADER + SEGMENT_UNKNOWN_SIZE + "1549a966" + "40")]
    ];
    for (const [what, bytes] of cases) {
      expect(withWebmDuration(bytes, 1_000), what).toBeNull();
    }
  });

  it("leaves a header whose checksum the patch would break", () => {
    const crc = element("bf", "00000000");
    const crcInSegment = hex(
      EBML_HEADER + SEGMENT_UNKNOWN_SIZE + crc + CHROME_INFO + CLUSTER_START
    );
    const crcInInfo = hex(
      EBML_HEADER +
        SEGMENT_UNKNOWN_SIZE +
        element("1549a966", crc + element("2ad7b1", "0f4240")) +
        CLUSTER_START
    );
    expect(withWebmDuration(crcInSegment, 1_000)).toBeNull();
    expect(withWebmDuration(crcInInfo, 1_000)).toBeNull();
  });
});

describe("withRecordedDuration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("patches only the header of a large first chunk and keeps the rest as it was", async () => {
    // Far past the header bytes read.
    const audio = new Uint8Array(100_000).fill(7);
    const chunk = new Blob([chromeWebm(), audio], { type: "audio/webm;codecs=opus" });

    const patched = new Uint8Array(await (await withRecordedDuration(chunk, 5_000)).arrayBuffer());

    expect(readDurationMs(patched)).toBe(5_000);
    expect(patched.subarray(patched.length - audio.length)).toEqual(audio);
  });

  it("leaves other formats unread", async () => {
    const chunk = new Blob([hex("0000001c6674797069736f6d")], { type: "audio/mp4" });
    const read = vi.spyOn(Blob.prototype, "arrayBuffer");

    expect(await withRecordedDuration(chunk, 1_000)).toBe(chunk);
    expect(read).not.toHaveBeenCalled();
  });

  it("keeps the chunk as it was when its header does not come in time", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    vi.spyOn(Blob.prototype, "arrayBuffer").mockImplementation(() => new Promise(() => undefined));
    const chunk = new Blob([chromeWebm()], { type: "audio/webm" });

    const result = withRecordedDuration(chunk, 1_000);
    await vi.advanceTimersByTimeAsync(2_000);

    expect(await result).toBe(chunk);
  });
});
