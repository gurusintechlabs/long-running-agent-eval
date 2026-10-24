import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface DataVersionValue {
  /** Include in a view's fetch deps: it changes after an ingest, so data reloads. */
  version: number;
  bump: () => void;
}

const Ctx = createContext<DataVersionValue>({ version: 0, bump: () => undefined });

export function DataVersionProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const value = useMemo(() => ({ version, bump }), [version, bump]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDataVersion(): DataVersionValue {
  return useContext(Ctx);
}
