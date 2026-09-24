import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ExpressionInput } from "./ExpressionInput";
import { parseJsonTemplate, resolveDeep, resolveExpression } from "@/lib/expressions";
import { EXPRESSION_MIME } from "@/lib/dnd";
import { cn } from "@/lib/utils";

export type ScalarFieldType = "string" | "number" | "json";

export function ScalarField({
  label,
  value,
  onChange,
  fieldType,
  outputs,
  placeholder,
  sensitive,
  required,
  compact,
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  fieldType: ScalarFieldType;
  outputs: Record<string, unknown>;
  placeholder?: string;
  sensitive?: boolean;
  required?: boolean;
  /** No label row, for inline use (e.g. a key/value row): the Fixed/Expression
   * toggle floats on the input's top edge instead, so the input lines up with
   * its neighbours. */
  compact?: boolean;
}) {
  const asString = value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);
  const [mode, setMode] = useState<"fixed" | "expression">(
    typeof value === "string" && value.includes("{{") ? "expression" : "fixed"
  );
  const [jsonText, setJsonText] = useState(() =>
    fieldType === "json" && typeof value !== "string" ? JSON.stringify(value ?? {}, null, 2) : asString
  );
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [dropHover, setDropHover] = useState(false);

  const acceptsDrop = (e: React.DragEvent) => e.dataTransfer.types.includes(EXPRESSION_MIME);

  const handleDropOnFixed = (e: React.DragEvent) => {
    if (!acceptsDrop(e)) return;
    e.preventDefault();
    setDropHover(false);
    const expr = e.dataTransfer.getData(EXPRESSION_MIME);
    if (fieldType === "json") {
      // Add the dropped field as a new key of the body object, instead of
      // replacing the whole body with a single expression string.
      const current = parseJsonTemplate(jsonText.trim() || "{}");
      if (current && typeof current === "object" && !Array.isArray(current)) {
        const obj = current as Record<string, unknown>;
        const base = expr.match(/\.(\w+)\s*\}\}$/)?.[1] ?? "value";
        let key = base;
        for (let n = 2; key in obj; n++) key = `${base}_${n}`;
        const next = { ...obj, [key]: expr };
        setJsonText(JSON.stringify(next, null, 2));
        setJsonError(null);
        onChange(next);
        return;
      }
    }
    setMode("expression");
    onChange(expr);
  };

  // A JSON body is resolved value by value, so a value that is exactly one
  // {{ }} expression keeps its real type (number, boolean, object).
  const jsonTemplate =
    fieldType === "json" ? parseJsonTemplate(mode === "expression" ? asString : jsonText) : undefined;
  const showResult = mode === "expression" || (fieldType === "json" && jsonText.includes("{{"));
  const result = !showResult
    ? undefined
    : fieldType === "json" && jsonTemplate !== undefined
      ? resolveDeep(jsonTemplate, outputs)
      : resolveExpression(asString, outputs);

  const toggle = (
    <span
      className={cn(
        "flex overflow-hidden rounded-md border border-line bg-surface opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100",
        mode === "expression" && "opacity-100"
      )}
    >
      <button
        type="button"
        onClick={() => {
          if (fieldType === "json" && mode === "expression") {
            const parsed = typeof value === "string" ? parseJsonTemplate(value) : value;
            setJsonText(parsed === undefined ? asString : JSON.stringify(parsed, null, 2));
            if (parsed !== undefined && typeof value === "string") onChange(parsed);
          }
          setMode("fixed");
        }}
        className={cn("px-1.5 py-0.5 text-[11px] text-ink-3", mode === "fixed" && "bg-ink text-white")}
      >
        Fixed
      </button>
      <button
        type="button"
        onClick={() => setMode("expression")}
        className={cn("px-1.5 py-0.5 text-[11px] text-ink-3", mode === "expression" && "bg-ink text-white")}
      >
        Expression
      </button>
    </span>
  );

  return (
    <div
      className={cn("group", compact ? "relative" : "mb-4")}
      onDragOver={(e) => {
        if (acceptsDrop(e)) {
          e.preventDefault();
          setDropHover(true);
        }
      }}
      onDragLeave={() => setDropHover(false)}
    >
      {compact ? (
        <div className="absolute -top-2.5 right-1.5 z-10">{toggle}</div>
      ) : (
        <label className="mb-1.5 flex items-center justify-between text-xs font-medium text-ink-2">
          <span>
            {label}
            {required && <span className="text-err"> *</span>}
          </span>
          {toggle}
        </label>
      )}

      <div
        onDrop={handleDropOnFixed}
        className={cn(dropHover && mode === "fixed" && "rounded-[7px] ring-2 ring-accent ring-offset-1")}
      >
        {mode === "expression" ? (
          <ExpressionInput value={asString} onChange={onChange} />
        ) : fieldType === "json" ? (
          <Textarea
            value={jsonText}
            placeholder={placeholder ?? "{}"}
            onChange={(e) => {
              const text = e.target.value;
              setJsonText(text);
              const parsed = parseJsonTemplate(text);
              if (parsed === undefined) {
                setJsonError("Invalid JSON");
              } else {
                onChange(parsed);
                setJsonError(null);
              }
            }}
          />
        ) : (
          <Input
            type={sensitive ? "password" : "text"}
            value={asString}
            placeholder={placeholder}
            onChange={(e) => {
              const text = e.target.value;
              if (fieldType === "number") {
                const num = Number(text);
                onChange(text === "" ? "" : Number.isNaN(num) ? text : num);
              } else {
                onChange(text);
              }
            }}
          />
        )}
      </div>
      {jsonError && mode === "fixed" && <div className="mt-1 text-xs text-err">{jsonError}</div>}

      {showResult && (
        <div className="mt-1.5 break-all font-mono text-xs text-ink-3">
          Result:{" "}
          <b className="font-medium text-ok">
            {result === undefined ? "test the upstream block to preview" : JSON.stringify(result)}
          </b>
        </div>
      )}
    </div>
  );
}
