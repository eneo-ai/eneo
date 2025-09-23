const unsupportedModels = ["o3-mini-azure", "o3-mini", "gpt-5-azure"];

export function supportsTemperature(modelName?: string): boolean {
  return modelName ? !unsupportedModels.includes(modelName) : false;
}
