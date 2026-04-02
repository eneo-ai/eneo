from __future__ import annotations


_KNOWLEDGE_PACK_EDIT_MODE = """\
## Redigeringsläge (Edit Mode)

Du redigerar ett befintligt flöde. Beskriv BARA ändringarna — backend bevarar allt annat.

### Nyckelregler
- Använd `op: "add"` för nya steg — ALDRIG `target_ref`
- I `add_payload` beskriver du bara det nya stegets avsikt: `name`, `instructions`, input/output-typ, eventuella kunskapsbaser, formfält och strukturerade `output_fields`
- Backend härleder `output_mode`, `input_bindings`, kontrakt och låg-nivå-konfiguration för nya steg
- Använd `op: "modify"` med `target_ref` för att ändra befintliga steg
- Använd `op: "remove"` med `target_ref` för att ta bort steg
- Steg du inte nämner bevaras automatiskt oförändrade
- Ändra bara de steg som faktiskt påverkas av användarens begäran
- Om du byter `output_type` eller `output_mode`, rensa inkompatibel `output_config` i patchen i stället för att lämna kvar gammal config
- Backend kompilerar dina operationer till en komplett förhandsvisning med diff

### Exempel 1: Infoga transkriberingssteg före befintlig analys
Användaren: "Lägg till ett steg som transkriberar ljud innan analysen"
→ Korrekt:
```json
{
  "operations": [
    {
      "op": "add",
      "placement": {"position": "before", "anchor_ref": "existing_step_1"},
      "add_payload": {
        "name": "Transkribera ljud",
        "instructions": "Transkribera ljudfilen till text.",
        "input_source": "flow_input",
        "input_type": "audio",
        "output_type": "text",
        "runtime_upload": true,
        "runtime_required": true
      }
    }
  ],
  "plan_rationale": "Lägger till transkribering som nytt steg 1, befintlig analys blir steg 2."
}
```

### Exempel 2: Lägg till sammanfattningssteg efter analys (bevara allt)
Användaren: "Lägg till ett sammanfattningssteg efter analysen"
→ Korrekt:
```json
{
  "operations": [
    {
      "op": "add",
      "placement": {"position": "after", "anchor_ref": "existing_step_2"},
      "add_payload": {
        "name": "Sammanfatta",
        "instructions": "Sammanfatta analysresultatet.",
        "input_source": "previous_step",
        "output_type": "text"
      }
    }
  ],
  "plan_rationale": "Nytt sammanfattningssteg efter befintlig analys. Alla andra steg oförändrade."
}
```

### Exempel 3: Omöjlig kombination → ställ fråga
Användaren: "Jag vill att flödet hanterar både ljudfiler och dokument"
→ Ställ en `flow_input_architecture`-fråga: ljud och dokument kräver olika `input_type` \
på första steget. Gissa ALDRIG — fråga vilken som är primär."""


__all__ = ["_KNOWLEDGE_PACK_EDIT_MODE"]
