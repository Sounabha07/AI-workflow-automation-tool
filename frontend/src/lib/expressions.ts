// Mirrors engine/resolver.py's PLACEHOLDER regex and lookup semantics,
// for previewing {{ block_id.path }} expressions in the block editor.

export const PLACEHOLDER = /\{\{(.*?)\}\}/g;

export function buildExpression(blockId: string, path: string): string {
  return path ? `{{ ${blockId}.${path} }}` : `{{ ${blockId} }}`;
}

/** True when the whole string is exactly one {{ }} token (no surrounding text). */
export function isWholeExpression(text: string): boolean {
  const m = text.trim().match(/^\{\{(.*)\}\}$/);
  return m !== null && !m[1].includes("{{");
}

function lookupPath(path: string, outputs: Record<string, unknown>): unknown {
  const segments = path.trim().split(".");
  const [blockId, ...fieldPath] = segments;
  if (!(blockId in outputs)) return undefined;
  let current: unknown = outputs[blockId];
  for (const segment of fieldPath) {
    if (typeof current !== "object" || current === null || !(segment in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

/** Resolves a value (which may embed one or more {{ }} tokens) against a map
 * of blockId -> output. Returns undefined if any token can't be resolved. */
export function resolveExpression(
  text: string,
  outputs: Record<string, unknown>
): unknown {
  const whole = text.trim().match(/^\{\{(.*)\}\}$/);
  if (whole && !whole[1].includes("{{")) {
    return lookupPath(whole[1], outputs);
  }

  let unresolved = false;
  const result = text.replace(PLACEHOLDER, (_match, inner: string) => {
    const value = lookupPath(inner, outputs);
    if (value === undefined) {
      unresolved = true;
      return "";
    }
    return typeof value === "string" ? value : JSON.stringify(value);
  });
  return unresolved ? undefined : result;
}

export interface ExpressionSegment {
  text: string;
  isToken: boolean;
}

/** Splits text into plain/token segments for syntax-highlighted rendering. */
export function highlightExpression(text: string): ExpressionSegment[] {
  const segments: ExpressionSegment[] = [];
  let lastIndex = 0;
  const regex = /\{\{.*?\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index), isToken: false });
    }
    segments.push({ text: match[0], isToken: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex), isToken: false });
  }
  return segments;
}

/** Rewrites every {{ oldId.<path> }} (or bare {{ oldId }}) reference to newId,
 * walking arbitrarily nested config. Used when a block is renamed (B7 Settings). */
export function renameReferences<T>(value: T, oldId: string, newId: string): T {
  if (typeof value === "string") {
    const renamed = value.replace(
      /\{\{\s*([a-z][a-z0-9_]*)((?:\.[\w]+)*)\s*\}\}/g,
      (match, blockId: string, path: string) =>
        blockId === oldId ? `{{ ${newId}${path} }}` : match
    );
    return renamed as unknown as T;
  }
  if (Array.isArray(value)) {
    return value.map((v) => renameReferences(v, oldId, newId)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = renameReferences(v, oldId, newId);
    }
    return out as unknown as T;
  }
  return value;
}

/** Parses a JSON body template. `{{ }}` tokens outside a JSON string are
 * quoted first, so `{"n": {{ a.count }}}` parses to `{"n": "{{ a.count }}"}`
 * and the resolver can then keep that value's real type. Mirrors
 * parse_json_template in engine/resolver.py. Returns undefined if invalid. */
export function parseJsonTemplate(text: string): unknown {
  let out = "";
  let inString = false;
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (inString) {
      out += ch;
      if (ch === "\\") {
        out += text[i + 1] ?? "";
        i += 2;
        continue;
      }
      if (ch === '"') inString = false;
      i++;
      continue;
    }
    if (ch === '"') {
      inString = true;
      out += ch;
      i++;
      continue;
    }
    if (text.startsWith("{{", i)) {
      const end = text.indexOf("}}", i + 2);
      if (end === -1) return undefined;
      out += JSON.stringify(text.slice(i, end + 2));
      i = end + 2;
      continue;
    }
    out += ch;
    i++;
  }
  try {
    return JSON.parse(out);
  } catch {
    return undefined;
  }
}

/** Resolves every string inside a nested value; undefined if any token can't be resolved. */
export function resolveDeep(value: unknown, outputs: Record<string, unknown>): unknown {
  if (typeof value === "string") return value.includes("{{") ? resolveExpression(value, outputs) : value;
  if (Array.isArray(value)) {
    const items = value.map((v) => resolveDeep(v, outputs));
    return items.some((v) => v === undefined) ? undefined : items;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      const r = resolveDeep(v, outputs);
      if (r === undefined) return undefined;
      out[k] = r;
    }
    return out;
  }
  return value;
}
