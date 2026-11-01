import { useRef, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { resolveExpression } from "@/lib/expressions";
import { EXPRESSION_MIME } from "@/lib/dnd";
import { cn } from "@/lib/utils";

/** A multi-line text field (e.g. an LLM prompt). {{ }} expressions can sit
 * anywhere in the text, so there's no Fixed/Expression toggle: a dragged
 * field is inserted at the caret, and the result preview appears once the
 * text contains an expression. */
export function TextField({
  label,
  value,
  onChange,
  outputs,
  placeholder,
  description,
  required,
}: {
  label: string;
  value: unknown;
  onChange: (value: string) => void;
  outputs: Record<string, unknown>;
  placeholder?: string;
  description?: string;
  required?: boolean;
}) {
  const text = value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);
  const ref = useRef<HTMLTextAreaElement>(null);
  const [dropHover, setDropHover] = useState(false);
  // Dragging from the input pane blurs the textarea, but its selection
  // survives the blur; only trust it once the user has placed the caret.
  const caretPlaced = useRef(false);

  const acceptsDrop = (e: React.DragEvent) => e.dataTransfer.types.includes(EXPRESSION_MIME);

  const handleDrop = (e: React.DragEvent<HTMLTextAreaElement>) => {
    if (!acceptsDrop(e)) return;
    e.preventDefault();
    setDropHover(false);
    const expr = e.dataTransfer.getData(EXPRESSION_MIME);
    const el = ref.current;
    // Insert where the caret was last left; at the end if it never was.
    const start = el && caretPlaced.current ? el.selectionStart : text.length;
    const end = el && caretPlaced.current ? el.selectionEnd : text.length;
    const next = text.slice(0, start) + expr + text.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(start + expr.length, start + expr.length);
    });
  };

  const hasExpression = text.includes("{{");
  const resolved = hasExpression ? resolveExpression(text, outputs) : undefined;
  // A prompt that is exactly one expression may resolve to an object; the
  // block sends that as JSON, so preview it the same way.
  const result = resolved === undefined || typeof resolved === "string" ? resolved : JSON.stringify(resolved);

  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-medium text-ink-2">
        {label}
        {required && <span className="text-err"> *</span>}
      </label>
      <Textarea
        ref={ref}
        rows={5}
        value={text}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onSelect={() => (caretPlaced.current = true)}
        onDragOver={(e) => {
          if (acceptsDrop(e)) {
            e.preventDefault();
            setDropHover(true);
          }
        }}
        onDragLeave={() => setDropHover(false)}
        onDrop={handleDrop}
        className={cn("font-sans text-[13px] leading-relaxed", dropHover && "ring-2 ring-accent ring-offset-1")}
      />
      {description && <div className="mt-1 text-[11px] text-ink-3">{description}</div>}
      {hasExpression && (
        <div className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-ink-3">
          Result:{" "}
          <b className="font-medium text-ok">{result === undefined ? "test the upstream block to preview" : result}</b>
        </div>
      )}
    </div>
  );
}
