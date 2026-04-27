export type AudioRecordingOptions = {
  mimeType?: string;
  audioBitsPerSecond: number;
};

export const SPEECH_OPUS_BITRATE = 24_000;
export const SPEECH_AAC_BITRATE = 64_000;

export function estimateRecordingBytes(
  durationSeconds: number,
  bitsPerSecond = SPEECH_OPUS_BITRATE
): number {
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return 0;
  if (!Number.isFinite(bitsPerSecond) || bitsPerSecond <= 0) return 0;
  return Math.ceil((durationSeconds * bitsPerSecond) / 8);
}

export function estimateRecordingDurationSeconds(
  maxBytes: number,
  bitsPerSecond = SPEECH_OPUS_BITRATE
): number {
  if (!Number.isFinite(maxBytes) || maxBytes <= 0) return 0;
  if (!Number.isFinite(bitsPerSecond) || bitsPerSecond <= 0) return 0;
  return Math.floor((maxBytes * 8) / bitsPerSecond);
}

const RECORDING_CANDIDATES: AudioRecordingOptions[] = [
  {
    mimeType: "audio/webm;codecs=opus",
    audioBitsPerSecond: SPEECH_OPUS_BITRATE
  },
  {
    mimeType: "audio/ogg;codecs=opus",
    audioBitsPerSecond: SPEECH_OPUS_BITRATE
  },
  {
    mimeType: "audio/mp4;codecs=mp4a.40.2",
    audioBitsPerSecond: SPEECH_AAC_BITRATE
  },
  {
    mimeType: "audio/mp4",
    audioBitsPerSecond: SPEECH_AAC_BITRATE
  },
  {
    mimeType: "video/webm;codecs=opus",
    audioBitsPerSecond: SPEECH_OPUS_BITRATE
  }
];

function canRecordMimeType(
  mimeType: string,
  isTypeSupported: (mimeType: string) => boolean
): boolean {
  try {
    return isTypeSupported(mimeType);
  } catch {
    return false;
  }
}

function defaultMimeSupportCheck(mimeType: string): boolean {
  if (typeof MediaRecorder === "undefined") {
    return false;
  }
  return MediaRecorder.isTypeSupported(mimeType);
}

export function selectAudioRecordingOptions(
  isTypeSupported: (mimeType: string) => boolean = defaultMimeSupportCheck
): AudioRecordingOptions {
  const candidate = RECORDING_CANDIDATES.find(({ mimeType }) =>
    mimeType ? canRecordMimeType(mimeType, isTypeSupported) : false
  );

  if (candidate?.mimeType) {
    return {
      mimeType: candidate.mimeType,
      audioBitsPerSecond: candidate.audioBitsPerSecond
    };
  }

  return {
    audioBitsPerSecond: SPEECH_AAC_BITRATE
  };
}
