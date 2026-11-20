/**
 * An automatic call uses the conversation revision the host observed.
 * The server rejects a stale approval before starting the tool, so the same
 * call can be offered for explicit confirmation. Other errors can come after
 * execution and must never replay a tool.
 * @template Result
 * @param {{
 *   automaticRevision?: number,
 *   invoke: (revision?: number) => Promise<Result>,
 *   confirm: () => Promise<boolean>
 * }} call
 * @returns {Promise<Result>}
 */
export async function runViewToolWithApproval({ automaticRevision, invoke, confirm }) {
  // Revision zero has no saved approval preference.
  if (automaticRevision !== undefined && automaticRevision > 0) {
    try {
      return await invoke(automaticRevision);
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !("status" in error && error.status === 409 && "code" in error && error.code === 9065)
      )
        throw error;
    }
  }
  if (!(await confirm())) throw new Error("The user did not allow the tool call");
  return invoke();
}
