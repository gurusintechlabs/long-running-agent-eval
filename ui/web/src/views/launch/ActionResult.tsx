import type { ErrInfo, JobResult } from "../../api";

export function ActionError({ err }: { err: ErrInfo }) {
  return (
    <div className="issues issues-bad" role="alert">
      <strong>
        {err.status ? `HTTP ${err.status}` : "Error"}
        {err.code ? ` ${err.code}` : ""}
      </strong>
      <div>{err.message}</div>
      {typeof err.extra.log_tail === "string" && <pre className="log-tail">{err.extra.log_tail}</pre>}
    </div>
  );
}

export function JobOutput({ job, label }: { job: JobResult; label: string }) {
  return (
    <div className="issues issues-ok" role="status">
      <strong>
        {label}: {job.finished === false ? "still running (check again later)" : job.exit_code === 0 || job.exit_code == null ? "finished" : `exit code ${job.exit_code}`}
      </strong>
      {job.output_tail && <pre className="log-tail">{job.output_tail}</pre>}
    </div>
  );
}
