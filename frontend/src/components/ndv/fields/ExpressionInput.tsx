import { useEffect, useRef, useState } from "react";
import { highlightExpression } from "@/lib/expressions";
import { EXPRESSION_MIME } from "@/lib/dnd";
import { cn } from "@/lib/utils";

const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

/** A contentEditable surface that highlights {{ }} tokens in accent color
 * once the field loses focus (live coloring while typing would fight the
 * caret), and accepts a dropped expression at the caret (B7). */
export function ExpressionInput({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (focused || !ref.current) return;
    ref.current.innerHTML = highlightExpression(value)
      .map((seg) =>
        seg.isToken
          ? `<span class="rounded bg-accent-bg px-0.5 text-accent">${escapeHtml(seg.text)}</span>`
          : escapeHtml(seg.text)
      )
      .join("");
  }, [value, focused]);

  return (
    <div
      ref={ref}
      role="textbox"
      aria-multiline="false"
      contentEditable
      suppressContentEditableWarning
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        setFocused(false);
        onChange(e.currentTarget.textContent ?? "");
      }}
      onInput={(e) => onChange(e.currentTarget.textContent ?? "")}
      onDrop={(e) => {
        const expr = e.dataTransfer.getData(EXPRESSION_MIME);
        if (!expr) return;
        e.preventDefault();
        e.stopPropagation();
        // Insert at the caret rather than always appending at the end.
        if (!document.execCommand("insertText", false, expr)) {
          onChange((value ? value + " " : "") + expr);
        } else {
          onChange(e.currentTarget.textContent ?? "");
        }
      }}
      className={cn(
        "min-h-[34px] whitespace-pre-wrap rounded-[7px] border border-[#B9C8F7] bg-[#F6F8FE] px-2.5 py-1.5 font-mono text-xs text-ink outline-none",
        className
      )}
    />
  );
}
