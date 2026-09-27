/**
 * Lets the user save `file`: through the browser's save dialog where it exists, otherwise as a
 * regular download. Cancelling the dialog is not an error; other failures are thrown.
 */
export async function downloadFile(file: Blob, suggestedName: string): Promise<void> {
  if (window.showSaveFilePicker) {
    try {
      const handle = await window.showSaveFilePicker({ suggestedName });
      const writable = await handle.createWritable();
      await writable.write(file);
      await writable.close();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      throw error;
    }
    return;
  }

  const a = document.createElement("a");
  a.download = suggestedName;
  a.href = URL.createObjectURL(file);
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
}

export function downloadTextFile(text: string, suggestedName: string): Promise<void> {
  return downloadFile(
    new Blob([text], { type: "application/octet-stream;charset=utf-8" }),
    suggestedName
  );
}
