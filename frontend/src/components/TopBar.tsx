import { GitMerge } from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

export function TopBar() {
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-5 border-b border-line bg-surface px-5">
      <span className="flex items-center gap-2 font-semibold">
        <GitMerge className="h-5 w-5 text-accent" aria-hidden="true" />
        Workflow builder
      </span>
      <nav className="flex h-full gap-1">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            cn(
              "flex h-full items-center border-b-2 border-transparent px-3 text-ink-3 no-underline",
              isActive && "border-ink text-ink"
            )
          }
        >
          Workflows
        </NavLink>
        <NavLink
          to="/history"
          className={({ isActive }) =>
            cn(
              "flex h-full items-center border-b-2 border-transparent px-3 text-ink-3 no-underline",
              isActive && "border-ink text-ink"
            )
          }
        >
          History
        </NavLink>
      </nav>
    </header>
  );
}
