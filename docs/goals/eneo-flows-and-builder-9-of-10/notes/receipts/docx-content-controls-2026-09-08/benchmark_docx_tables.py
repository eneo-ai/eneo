"""Measure the public document rendering service; print every raw timing."""

import json
import platform
import sys
from time import perf_counter

from eneo.flows.runtime.document_rendering.service import default_document_render_service

service = default_document_render_service()
print(json.dumps({"python": sys.version.split()[0], "platform": platform.platform()}))
for cells in (250, 500, 1000, 2000):
    columns = 10
    lines = ["|" + "|".join(f"Column {n}" for n in range(columns)) + "|",
             "|" + "|".join("---" for _ in range(columns)) + "|"]
    lines += ["|" + "|".join(f"Cell {row}-{col}" for col in range(columns)) + "|"
              for row in range(cells // columns - 1)]
    markdown = "\n".join(lines)
    service.render_document(markdown, "docx", step_order=1)
    for repetition in range(1, 4):
        start = perf_counter()
        document, _, _ = service.render_document(markdown, "docx", step_order=1)
        seconds = perf_counter() - start
        print(json.dumps({"cells_including_header": cells, "repetition": repetition,
                          "seconds": round(seconds, 6), "output_bytes": len(document)}), flush=True)
