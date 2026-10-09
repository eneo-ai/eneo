export type TabularColumn = {
  name: string;
  type: string;
  profile?: {
    distinctCount: number;
    /** Every distinct value, for low-cardinality columns. */
    values?: string[];
    min?: string;
    max?: string;
    /** A few values of a high-cardinality text column, showing its format. */
    examples?: string[];
    /** How to cast a text column that holds numbers or dates in a local format. */
    hint?: string;
  };
};
