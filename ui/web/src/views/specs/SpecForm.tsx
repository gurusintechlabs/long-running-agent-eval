import { useMemo } from "react";
import type { SpecData, SpecSchema } from "../../api";
import { ExtraField, FieldList } from "./fields";
import { FormCtx, type FormCtxValue } from "./formContext";
import { findExtraKeys, issuesUnder, sectionBlocks, setAt, splitPath, type IssueIndex, type Json, type SectionBlock } from "./formLogic";

export interface SpecFormProps {
  schema: SpecSchema;
  data: SpecData;
  /** Functional update so rapid edits never act on a stale copy. */
  edit: (fn: (d: SpecData) => SpecData) => void;
  readOnly?: boolean;
  errors: IssueIndex;
  warnings: IssueIndex;
  open: ReadonlySet<string>;
  setOpen: (key: string, open: boolean) => void;
}

export function blockIssueCount(block: SectionBlock, errors: IssueIndex): number {
  return block.roots.reduce((n, r) => n + issuesUnder(errors, r.path), 0);
}

export function SpecForm({ schema, data, edit, readOnly = false, errors, warnings, open, setOpen }: SpecFormProps) {
  const blocks = useMemo(() => sectionBlocks(schema), [schema]);
  const extras = useMemo(() => findExtraKeys(schema.fields, data), [schema, data]);
  const ctx: FormCtxValue = useMemo(
    () => ({
      data,
      set: (path: string, value: Json) => edit((d) => setAt(d, splitPath(path), value)),
      readOnly,
      errors,
      warnings,
      crossNotes: schema.cross_field_notes ?? [],
      open,
      setOpen,
    }),
    [data, edit, readOnly, errors, warnings, schema, open, setOpen],
  );
  return (
    <FormCtx.Provider value={ctx}>
      <div className="spec-form">
        {blocks.map((b) => {
          const issues = blockIssueCount(b, errors);
          const key = `sec:${b.section.id}`;
          const collapsible = b.allAdvanced;
          const isOpen = !collapsible || open.has(key) || issues > 0;
          return (
            <section key={b.section.id} id={`sec-${b.section.id}`} className="sec" aria-labelledby={`sech-${b.section.id}`}>
              <header className="sec-head">
                <h2 id={`sech-${b.section.id}`}>
                  {collapsible ? (
                    <button type="button" className="sec-toggle" aria-expanded={isOpen} onClick={() => setOpen(key, !isOpen)}>
                      <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span> {b.section.label}
                    </button>
                  ) : (
                    b.section.label
                  )}
                </h2>
                {collapsible && <span className="tag-adv">advanced</span>}
                {issues > 0 && (
                  <span className="count-bad">
                    {issues} issue{issues === 1 ? "" : "s"}
                  </span>
                )}
              </header>
              {isOpen && (
                <div className="sec-body">
                  {b.section.help && <p className="sec-help">{b.section.help}</p>}
                  <FieldList fields={b.roots} base="" indices={[]} bareRoots inAdvanced={false} />
                </div>
              )}
            </section>
          );
        })}
        {extras.length > 0 && (
          <section id="sec-unknown" className="sec">
            <header className="sec-head">
              <h2>Other fields in this spec</h2>
            </header>
            <div className="sec-body">
              <p className="sec-help">
                These keys are not in the form schema. They are kept as they are (editable as JSON) so nothing is lost; the
                server decides whether they are valid.
              </p>
              {extras.map((p) => (
                <ExtraField key={p} path={p} />
              ))}
            </div>
          </section>
        )}
      </div>
    </FormCtx.Provider>
  );
}
