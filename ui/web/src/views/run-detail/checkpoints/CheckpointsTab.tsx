import { useSearchParams } from "react-router-dom";
import type { CheckpointRow } from "../../../api";
import { Card, ErrorState, Spinner } from "../../../components";
import { CheckpointsTable } from "../CheckpointsTable";
import { CheckpointDrawer } from "./CheckpointDrawer";

export function CheckpointsTab({
  runId,
  checkpoints,
  ingested,
  loading,
  error,
  onRetry,
}: {
  runId: string;
  checkpoints: CheckpointRow[];
  ingested: boolean;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const kParam = params.get("k");
  const k = kParam != null && /^\d{1,6}$/.test(kParam) ? Number(kParam) : null;

  const open = (n: number) => {
    const p = new URLSearchParams(params);
    p.set("tab", "checkpoints");
    p.set("k", String(n));
    setParams(p);
  };
  const close = () => {
    const p = new URLSearchParams(params);
    p.delete("k");
    setParams(p);
  };

  if (error && checkpoints.length === 0) return <Card><ErrorState title="Could not load checkpoints" error={error} onRetry={onRetry} /></Card>;
  if (loading && checkpoints.length === 0) return <Spinner label="Loading checkpoints" />;
  return (
    <>
      <CheckpointsTable checkpoints={checkpoints} ingested={ingested} onOpen={open} />
      {k != null && <CheckpointDrawer runId={runId} k={k} row={checkpoints.find((c) => c.k === k) ?? null} onClose={close} />}
    </>
  );
}
