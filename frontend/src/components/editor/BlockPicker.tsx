import { useState, type RefObject } from "react";
import { ChevronDown } from "lucide-react";
import { useBlockSchemas } from "@/hooks/useBlockSchemas";
import { useAddBlock } from "@/hooks/useAddBlock";
import { CATEGORY_ORDER, COLOR_BG_CLASS, blockVisual } from "@/lib/blockVisuals";
import { cn } from "@/lib/utils";

const CATEGORY_DOT_CLASS: Record<string, string> = {
  Triggers: "bg-trigger",
  Flow: "bg-flow",
  Data: "bg-data",
  Actions: "bg-action",
  Communication: "bg-ink-3",
};

export function BlockPicker({ wrapperRef }: { wrapperRef: RefObject<HTMLDivElement | null> }) {
  const { data: schemas = [] } = useBlockSchemas();
  const [category, setCategory] = useState<string>(CATEGORY_ORDER[0]);
  const addBlock = useAddBlock();

  const byCategory = (cat: string) => schemas.filter((s) => s.schema.category === cat);
  const blocks = byCategory(category);

  const addAtCenter = (type: string) => {
    const rect = wrapperRef.current?.getBoundingClientRect();
    const center = rect
      ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
      : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    addBlock(type, center);
  };

  return (
    <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2">
      <label className="flex items-center gap-2 text-xs text-ink-3" htmlFor="catSelect">
        Category
        <span className="relative flex items-center">
          <span
            className={cn("pointer-events-none absolute left-2.5 h-2 w-2 rounded-full", CATEGORY_DOT_CLASS[category])}
          />
          <select
            id="catSelect"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="min-w-[170px] cursor-pointer appearance-none rounded-[7px] border border-line-2 bg-surface py-1.5 pl-7 pr-7 text-[13px] font-medium text-ink hover:border-[#8E98A8]"
          >
            {CATEGORY_ORDER.map((c) => (
              <option key={c} value={c}>
                {c} ({byCategory(c).length})
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-ink-3" />
        </span>
      </label>

      <span className="h-6 w-px self-stretch bg-line" />

      <div className="flex min-h-[34px] flex-1 items-center gap-1.5 overflow-x-auto">
        {blocks.length === 0 && (
          <span className="text-xs text-ink-3">
            Slack, email, WhatsApp and more are coming to this category.
          </span>
        )}
        {blocks.map(({ type, schema }) => {
          const visual = blockVisual(type);
          const Icon = visual.icon;
          return (
            <div
              key={type}
              draggable
              tabIndex={0}
              title={`${schema.description ?? ""}. Click to add, or drag onto the canvas.`}
              onDragStart={(e) => e.dataTransfer.setData("application/x-block-type", type)}
              onClick={() => addAtCenter(type)}
              onKeyDown={(e) => e.key === "Enter" && addAtCenter(type)}
              className="flex cursor-grab items-center gap-2 whitespace-nowrap rounded-lg border border-line bg-surface py-1 pl-1 pr-2.5 text-[13px] hover:border-line-2 hover:bg-panel focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span className={cn("grid h-6 w-6 place-items-center rounded-md text-white", COLOR_BG_CLASS[visual.color])}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              {schema.name}
            </div>
          );
        })}
      </div>
    </div>
  );
}
