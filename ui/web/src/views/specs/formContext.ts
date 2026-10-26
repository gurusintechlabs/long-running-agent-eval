import { createContext, useContext } from "react";
import type { CrossFieldNote, SpecData } from "../../api";
import type { IssueIndex, Json } from "./formLogic";

export interface FormCtxValue {
  data: SpecData;
  /** Set (or with `undefined`, delete) the value at a concrete dotted path. */
  set: (path: string, value: Json) => void;
  readOnly: boolean;
  errors: IssueIndex;
  warnings: IssueIndex;
  crossNotes: CrossFieldNote[];
  /** Open disclosure panels: `adv:<path>` for Advanced groups, `sec:<id>` for collapsed sections. */
  open: ReadonlySet<string>;
  setOpen: (key: string, open: boolean) => void;
}

export const FormCtx = createContext<FormCtxValue | null>(null);

export function useForm(): FormCtxValue {
  const v = useContext(FormCtx);
  if (!v) throw new Error("form context missing");
  return v;
}
