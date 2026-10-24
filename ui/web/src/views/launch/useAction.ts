import { useCallback, useState } from "react";
import { errInfo, type ErrInfo } from "../../api";

/** Run one POST action and keep its busy / result / error state. Errors keep the server's text and code. */
export function useAction<T>() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<T | null>(null);
  const [err, setErr] = useState<ErrInfo | null>(null);
  const run = useCallback(async (fn: () => Promise<T>) => {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await fn();
      setResult(r);
      return r;
    } catch (e) {
      setErr(errInfo(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);
  const reset = useCallback(() => {
    setResult(null);
    setErr(null);
  }, []);
  return { busy, result, err, run, reset };
}
