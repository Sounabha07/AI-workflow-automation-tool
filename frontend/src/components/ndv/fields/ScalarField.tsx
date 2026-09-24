import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ExpressionInput } from "./ExpressionInput";
import { isWholeExpression, resolveExpression } from "@/lib/expressions";
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
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  fieldType: ScalarFieldType;
  outputs: Record<string, unknown>;
  placeholder?: string;
  sensitive?: boolean;
  required?: boolean;
}) {
  const asString = value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);
  const [mode, setMode] = useState<"fixed" | "expression">(
    typeof value === "string" && isWholeExpression(value) ? "expression" : "fixed"
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
    setMode("expression");
    onChange(expr);
  };

  const result = mode === "expression" ? resolveExpression(asString, outputs) : undefined;

  return (
    <div
      className="group mb-4"
      onDragOver={(e) => {
        if (acceptsDrop(e)) {
          e.preventDefault();
          setDropHover(true);
        }
      }}
      onDragLeave={() => setDropHover(false)}
    >
      <label className="mb-1.5 flex items-center justify-between text-xs font-medium text-ink-2">
        <span>
          {label}
          {required && <span className="text-err"> *</span>}
        </span>
        <span
          className={cn(
            "flex overflow-hidden rounded-md border border-line opacity-0 transition-opacity group-hover:opacity-100",
            mode === "expression" && "opacity-100"
          )}
        >
          <button
            type="button"
            onClick={() => setMode("fixed")}
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
      </label>

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
              try {
                onChange(JSON.parse(text));
                setJsonError(null);
              } catch {
                setJsonError("Invalid JSON");
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

      {mode === "expression" && (
        <div className="mt-1.5 font-mono text-xs text-ink-3">
          Result:{" "}
          <b className="font-medium text-ok">
            {result === undefined ? "test the upstream block to preview" : JSON.stringify(result)}
          </b>
        </div>
      )}
    </div>
  );
}
