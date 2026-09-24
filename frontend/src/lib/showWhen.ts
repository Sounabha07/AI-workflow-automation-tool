import type { ShowWhenValue } from "@/api/types";

/** A7 semantics: every key in show_when must match the current config;
 * a list value means "any of these". */
export function isFieldVisible(
  showWhen: Record<string, ShowWhenValue> | undefined,
  config: Record<string, unknown>
): boolean {
  if (!showWhen) return true;
  return Object.entries(showWhen).every(([key, expected]) => {
    const actual = config[key];
    if (Array.isArray(expected)) return expected.includes(actual as never);
    return actual === expected;
  });
}
