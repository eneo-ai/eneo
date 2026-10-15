/**
 * The extension of a file name in upper case, as shown beside a file: "PDF",
 * "DOCX". A name without one (including a dotfile or a trailing dot) gives "".
 */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toUpperCase();
}
