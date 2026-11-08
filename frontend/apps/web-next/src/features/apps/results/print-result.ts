import "./print-result.css";

/** Print only the selected, already-rendered result through the browser dialog. */
export function printResult(element: HTMLElement) {
  const document = element.ownerDocument;
  const printDocument = element.cloneNode(true);
  if (!(printDocument instanceof HTMLElement)) return;
  printDocument.setAttribute("data-app-result-print-document", "");
  document.body.append(printDocument);
  document.body.setAttribute("data-app-result-printing", "");
  try {
    window.print();
  } finally {
    printDocument.remove();
    document.body.removeAttribute("data-app-result-printing");
  }
}
