/**
 * The specialist each of an answer's references came through.
 *
 * A specialist's sources reach the orchestrating answer as ordinary reference
 * rows with the same id as in the consultation, so the consultation that
 * holds a reference id names the specialist it came via. References the
 * orchestrator found itself are absent from the map.
 */
export type ConsultationReferencesLike = {
  assistant_name: string;
  references?: Array<{ id: string }> | null;
};

export function specialistsByReference(
  consultations: ConsultationReferencesLike[] | null | undefined
): Map<string, string> {
  const byReference = new Map<string, string>();
  for (const consultation of consultations ?? []) {
    for (const reference of consultation.references ?? []) {
      if (!byReference.has(reference.id)) {
        byReference.set(reference.id, consultation.assistant_name);
      }
    }
  }
  return byReference;
}
