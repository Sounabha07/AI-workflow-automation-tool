import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import type { BlockSchemaResponse } from "@/api/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { blockVisual, COLOR_BG_CLASS } from "@/lib/blockVisuals";
import { switchOutputs } from "@/lib/nodeSubtitle";
import { FieldRenderer } from "./fields/FieldRenderer";
import { useEditorStore } from "@/store/editor";
import type { FlowNode } from "@/lib/definition";
import { cn } from "@/lib/utils";

const ID_PATTERN = /^[a-z][a-z0-9_]{0,62}$/;

export function ParametersPane({
  node,
  schema,
  outputs,
  onTestStep,
  testing,
}: {
  node: FlowNode;
  schema: BlockSchemaResponse["schema"] | undefined;
  outputs: Record<string, unknown>;
  onTestStep: () => void;
  testing: boolean;
}) {
  const visual = blockVisual(node.data.blockType);
  const Icon = visual.icon;
  const nodes = useEditorStore((s) => s.nodes);
  const updateNodeConfig = useEditorStore((s) => s.updateNodeConfig);
  const updateNodeNotes = useEditorStore((s) => s.updateNodeNotes);
  const removeEdgesForOutputs = useEditorStore((s) => s.removeEdgesForOutputs);
  const renameNode = useEditorStore((s) => s.renameNode);
  const markDirty = useEditorStore((s) => s.markDirty);

  const [idDraft, setIdDraft] = useState(node.id);
  const [idError, setIdError] = useState("");

  // Display and show_when must read the same state. A saved config may omit a
  // field (its schema default applies), so merge the defaults in first.
  const effectiveConfig: Record<string, unknown> = { ...node.data.config };
  for (const f of schema?.fields ?? []) {
    if (effectiveConfig[f.name] === undefined && f.default !== undefined) effectiveConfig[f.name] = f.default;
  }

  const handleFieldChange = (name: string, value: unknown) => {
    const before = node.data.blockType === "switch" ? switchOutputs(node.data.config) : [];
    updateNodeConfig(node.id, (c) => ({ ...c, [name]: value }));
    markDirty();
    if (node.data.blockType === "switch" && (name === "rules" || name === "fallback")) {
      const after = switchOutputs({ ...node.data.config, [name]: value });
      const removed = before.filter((o) => !after.includes(o));
      if (removed.length) removeEdgesForOutputs(node.id, removed);
    }
  };

  const commitRename = () => {
    const trimmed = idDraft.trim();
    if (trimmed === node.id) {
      setIdError("");
      return;
    }
    if (!ID_PATTERN.test(trimmed)) {
      setIdError("Use lowercase letters, numbers and underscores, starting with a letter.");
      return;
    }
    if (nodes.some((n) => n.id === trimmed)) {
      setIdError("A block with this id already exists.");
      return;
    }
    renameNode(node.id, trimmed);
    markDirty();
    setIdError("");
  };

  if (node.data.blockType === "manual_trigger") {
    return (
      <>
        <Header node={node} Icon={Icon} color={visual.color} onTestStep={onTestStep} testing={testing} hideTest />
        <div className="grid h-full place-items-center p-6 text-center text-[13px] text-ink-3">
          This block has no parameters. It starts the workflow when you click Run workflow.
        </div>
      </>
    );
  }

  return (
    <>
      <Header node={node} Icon={Icon} color={visual.color} onTestStep={onTestStep} testing={testing} />
      <Tabs defaultValue="params" className="flex min-h-0 flex-1 flex-col">
        <div className="border-b border-line px-4">
          <TabsList>
            <TabsTrigger value="params">Parameters</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="params" className="min-h-0 flex-1 overflow-auto p-4">
          {(schema?.fields ?? []).map((f) => (
            <FieldRenderer key={f.name} field={f} config={effectiveConfig} outputs={outputs} onChange={handleFieldChange} />
          ))}
          {(schema?.fields ?? []).length === 0 && (
            <p className="text-[13px] text-ink-3">This block has no parameters.</p>
          )}
        </TabsContent>
        <TabsContent value="settings" className="min-h-0 flex-1 overflow-auto p-4">
          <div className="mb-4">
            <Label htmlFor="settings-id">Block ID</Label>
            <Input
              id="settings-id"
              className="mt-1.5"
              value={idDraft}
              onChange={(e) => setIdDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
            />
            {idError && <p className="mt-1 text-xs text-err">{idError}</p>}
          </div>
          <div className="mb-4">
            <Label>Block type</Label>
            <p className="mt-1.5 text-[13px] text-ink-2">{schema?.name ?? node.data.blockType}</p>
          </div>
          <div>
            <Label htmlFor="settings-notes">Notes</Label>
            <Textarea
              id="settings-notes"
              className="mt-1.5 font-sans text-[13px]"
              value={node.data.notes}
              onChange={(e) => {
                updateNodeNotes(node.id, e.target.value);
                markDirty();
              }}
              rows={4}
            />
          </div>
        </TabsContent>
      </Tabs>
    </>
  );
}

function Header({
  node,
  Icon,
  color,
  onTestStep,
  testing,
  hideTest,
}: {
  node: FlowNode;
  Icon: React.ComponentType<{ className?: string }>;
  color: "trigger" | "flow" | "data" | "action";
  onTestStep: () => void;
  testing: boolean;
  hideTest?: boolean;
}) {
  return (
    <div className="border-b border-line px-4 pt-3.5">
      <div className="flex items-center gap-2.5">
        <span className={cn("grid h-7 w-7 place-items-center rounded-[7px] text-white", COLOR_BG_CLASS[color])}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="flex-1 rounded px-1 py-1 text-[15px] font-semibold">{node.id}</span>
        {!hideTest && (
          <Button variant="test" onClick={onTestStep} disabled={testing}>
            {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />}
            {testing ? "Testing" : "Test step"}
          </Button>
        )}
      </div>
    </div>
  );
}
