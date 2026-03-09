import { getFlowRuntimeErrorMessage } from "./flowRuntimeErrorMapping";

export function getTemplateFillErrorMessage(
  error: unknown,
  fallbackMessage: string
): string {
  return getFlowRuntimeErrorMessage(error, fallbackMessage);
}
