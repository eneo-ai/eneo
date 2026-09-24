export type TabularColumn = {
  name: string;
  type: string;
  profile?: { distinctCount: number; values?: string[]; min?: string; max?: string };
};
