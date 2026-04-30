// Why a separate "rotation" reason instead of overloading "manual": the
// session needs to tell apart a timer-driven stop (start the next
// segment) from a user-initiated stop (finish the session). Without
// this distinction the dialog would either silently keep recording
// after the user pressed Stop, or stop after every rotation tick.
export type RecordingStopReason = "manual" | "limit" | "stall" | "error" | "rotation";

function inferRecordedAudioExtension(mimeType: string): string {
  const normalized = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";
  switch (normalized) {
    case "audio/mp4":
    case "video/mp4":
      return "m4a";
    case "audio/webm":
    case "video/webm":
      return "webm";
    case "audio/mpeg":
      return "mp3";
    default: {
      const subtype = normalized.split("/")[1];
      return subtype && subtype.length > 0 ? subtype : "audio";
    }
  }
}

export function buildRecordedAudioFile(params: {
  blob: Blob;
  mimeType: string;
  fileNameBase: string;
}): File {
  const extension = inferRecordedAudioExtension(params.mimeType);
  return new File([params.blob], `${params.fileNameBase}.${extension}`, {
    type: params.mimeType
  });
}
