export type RecordedAudioSaveResult = "saved" | "downloaded" | "cancelled";

export async function downloadRecordedAudioFile(file: File): Promise<RecordedAudioSaveResult> {
  if (typeof window === "undefined") {
    throw new Error("Recording downloads are only available in the browser.");
  }

  if (window.showSaveFilePicker) {
    try {
      const handle = await window.showSaveFilePicker({ suggestedName: file.name });
      const writable = await handle.createWritable();
      await writable.write(file);
      await writable.close();
      return "saved";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return "cancelled";
      }
      throw error;
    }
  }

  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.download = file.name;
  anchor.href = url;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
  return "downloaded";
}
