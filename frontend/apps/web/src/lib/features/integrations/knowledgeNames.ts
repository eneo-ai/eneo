/** The longest name the server takes for an imported source or its group, in characters. */
export const KNOWLEDGE_NAME_MAX_LENGTH = 255;

/** A name cut to what the server takes, counting characters as the server does. */
export function fitKnowledgeName(name: string): string {
  const characters = Array.from(name);
  return characters.length > KNOWLEDGE_NAME_MAX_LENGTH
    ? characters.slice(0, KNOWLEDGE_NAME_MAX_LENGTH).join("")
    : name;
}
