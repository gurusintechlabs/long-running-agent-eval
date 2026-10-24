import { useState } from "react";
import { controlApi, type JobResult } from "../../api";
import { Dialog } from "../../components";
import { ActionError, JobOutput } from "./ActionResult";
import { useAction } from "./useAction";

/** Global `lrae clean`: recovers crashed runs, reaps leftover agent processes and state. */
export function CleanButton({ disabled = false, className = "btn" }: { disabled?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  const act = useAction<JobResult>();
  return (
    <>
      <button type="button" className={className} disabled={disabled} onClick={() => setOpen(true)} title={disabled ? "Not available while a run is active" : undefined}>
        Clean…
      </button>
      {open && (
        <Dialog
          title="Clean up (lrae clean)"
          onClose={() => {
            setOpen(false);
            act.reset();
          }}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setOpen(false)}>
                Close
              </button>
              <button type="button" className="btn btn-primary" disabled={act.busy || !!act.result} onClick={() => void act.run(() => controlApi.clean())}>
                {act.busy ? "Cleaning…" : "Run clean"}
              </button>
            </>
          }
        >
          <p>
            Clean is <strong>global</strong>: it finalizes every unfinished run whose harness is gone (state INTERRUPTED, marked recovered), reaps leftover agent
            processes and fixtures, deletes agent state directories and restores user memory. It does not spend and does not touch a running harness (it is refused
            while a run is active).
          </p>
          {act.err && <ActionError err={act.err} />}
          {act.result && <JobOutput job={act.result} label="Clean" />}
        </Dialog>
      )}
    </>
  );
}
