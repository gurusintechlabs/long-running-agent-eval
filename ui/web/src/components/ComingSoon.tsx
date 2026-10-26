import { Card } from "./Card";
import { EmptyState } from "./States";

/** Placeholder body for views that a later phase fills in. */
export function ComingSoon({ title, phase, children }: { title: string; phase: string; children?: string }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <div className="page-sub">Planned for phase {phase}</div>
        </div>
      </div>
      <Card>
        <EmptyState title="Not built yet">{children ?? `This view arrives in phase ${phase} (docs/ui-plan.md).`}</EmptyState>
      </Card>
    </>
  );
}
