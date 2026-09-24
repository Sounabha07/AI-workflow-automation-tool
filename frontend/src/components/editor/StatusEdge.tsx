import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";
import type { FlowEdge } from "@/lib/definition";
import { useEditorStore } from "@/store/editor";

export function StatusEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  source,
  data,
}: EdgeProps<FlowEdge>) {
  const sourceState = useEditorStore((s) => s.blockStates[source]);
  const status = sourceState?.status ?? "idle";
  const branchTaken =
    sourceState?.output && typeof sourceState.output.branch_taken === "string"
      ? sourceState.output.branch_taken
      : undefined;

  const output = data?.output;
  const taken = output === undefined || branchTaken === output;
  const live = status === "succeeded" && taken;
  const dead = status === "skipped" || (status === "succeeded" && !taken);

  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const stroke = live ? "#6FBF93" : dead ? "#C5CCD6" : "#9AA4B2";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke,
          strokeWidth: 2,
          strokeDasharray: dead ? "4 4" : undefined,
        }}
      />
      {live && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className="rounded bg-canvas px-1.5 py-0.5 text-[11px] font-medium text-ok"
          >
            1 item
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
