from __future__ import annotations

OUTPUT_CHANGE_KEYWORDS: tuple[str, ...] = (
    "structured json",
    "structured_text",
    "structured text",
    "slut-pdf",
    "final pdf",
    "pdf-dokument",
    "pdf document",
    "docx-dokument",
    "docx document",
    "text summary",
    "textsammanfattning",
)

RUNTIME_METADATA_KEYWORDS: tuple[str, ...] = (
    "case number",
    "committee",
    "språk",
    "language",
    "fokus",
    "focus",
    "metadata",
    "form fields",
    "formulärfält",
)

STRUCTURED_EXTRACTION_KEYWORDS: tuple[str, ...] = (
    "structured data",
    "strukturerad data",
    "json",
    "output contract",
    "output_contract",
    "extrahera viktiga fakta",
    "risker",
    "möjligheter",
    "rekommendationer",
    "key facts",
    "risks",
    "opportunities",
    "recommendations",
)

DOCX_TEMPLATE_MODE_MARKERS: tuple[str, ...] = (
    "template fill",
    "template_fill",
    "template",
    "mall",
    "fylla i",
)

DOCX_GENERATED_MODE_MARKERS: tuple[str, ...] = (
    "utan mall",
    "without template",
)

DOCX_CONTEXT_MARKERS: tuple[str, ...] = (
    "docx",
    "word",
    "word-dokument",
    "word document",
)

PDF_TEMPLATE_EXPECTATION_MARKERS: tuple[str, ...] = (
    "pdf mall",
    "pdf-mall",
    "pdf template",
    "pdf-template",
    "template pdf",
    "fillable pdf",
    "fixed pdf layout",
    "fast pdf layout",
    "specific pdf layout",
    "specifik pdf layout",
)

PDF_TEMPLATE_GENERIC_MARKERS: tuple[str, ...] = (
    "mall",
    "template",
    "fylla i",
    "fyll i",
    "fixed layout",
    "fast layout",
    "specific layout",
    "specifik layout",
)

PDF_GENERATED_MODE_MARKERS: tuple[str, ...] = (
    "generated pdf",
    "vanlig pdf",
    "normal pdf",
    "utan mall",
    "without template",
)

PDF_OUTPUT_CONTEXT_MARKERS: tuple[str, ...] = (
    "slut pdf",
    "slut-pdf",
    "final pdf",
    "ny pdf",
    "pdf-rapport",
    "pdf rapport",
    "pdf report",
    "pdf-dokument",
    "pdf document",
    "rapport som pdf",
    "report as pdf",
    "slutrapport som pdf",
    "slutresultat som pdf",
    "resultat som pdf",
    "output as pdf",
    "skapa en pdf",
    "skapa pdf",
    "generera en pdf",
    "generera pdf",
    "skriv en pdf",
    "write a pdf",
    "create a pdf",
    "create pdf",
    "generate a pdf",
    "generate pdf",
    "vara en pdf",
    "be a pdf",
    "vanlig pdf",
    "normal pdf",
    "generated pdf",
    "pdf mall",
    "pdf-mall",
    "pdf template",
    "pdf-template",
)
