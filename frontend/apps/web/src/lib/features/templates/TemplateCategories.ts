// Predefined category types - kept for backward compatibility
type PredefinedAssistantCategory = "communication" | "q&a" | "misc" | "advice";
type PredefinedAppCategory = "transcription" | "misc";

// Predefined categories with localized titles and descriptions
export const assistantTemplateCategories: Record<
  PredefinedAssistantCategory,
  { title: string; description: string }
> = {
  communication: {
    title: "Kommunikation",
    description: "Assistenter som förbättrar tydlighet och kvalitet i din kommunikation."
  },
  "q&a": {
    title: "Frågor & Svar",
    description: "Assistenter som ger informativa och klara svar på vanliga frågor."
  },
  advice: {
    title: "Rådgivning",
    description: "Assistenter som vägleder genom beslutsfattande och kreativa processer."
  },
  misc: {
    title: "Övrigt",
    description: "Diverse assistenter för olika behov och uppgifter."
  }
};

export const appTemplateCategories: Record<
  PredefinedAppCategory,
  { title: string; description: string }
> = {
  transcription: {
    title: "Transkription",
    description: "Appar som hjälper till med att transkribera och dokumentera tal och möten."
  },
  misc: {
    title: "Övrigt",
    description: "Diverse appar för olika funktioner och behov."
  }
};

/**
 * Converts a category name to a human-readable title.
 * Examples:
 * - "test" -> "Test"
 * - "custom-category" -> "Custom Category"
 * - "my_category" -> "My Category"
 */
export function formatCategoryTitle(category: string): string {
  return category
    .split(/[-_\s]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

/**
 * Gets category information for any category string.
 * If the category is predefined, returns localized title/description.
 * If the category is custom (tenant-created), generates title from category name.
 */
export function getCategoryInfo(
  category: string,
  predefinedCategories: Record<string, { title: string; description: string }>
): { title: string; description: string } {
  // Check if it's a predefined category
  if (category in predefinedCategories) {
    return predefinedCategories[category];
  }

  // Generate title and description for custom categories
  const title = formatCategoryTitle(category);
  return {
    title,
    description: `${title} templates`
  };
}
