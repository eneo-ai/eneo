const dynamicColours = ["eneo", "pine", "moss", "amethyst", "blue"] as const;

function generateColour(id: string) {
  let sum = 0;
  for (let i = 0; i < id.length; i++) {
    sum += id.charCodeAt(i) * id.charCodeAt(i > 1 ? i - 1 : i);
  }
  return sum % dynamicColours.length;
}

export function dynamicColour(options: { basedOn: string }) {
  return { "data-dynamic-colour": dynamicColours[generateColour(options.basedOn)] };
}
