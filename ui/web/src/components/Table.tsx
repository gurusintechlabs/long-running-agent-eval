import { useMemo, useState, type ReactNode } from "react";

export type SortValue = number | string | null | undefined;

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Cell content. Strings are rendered as text by React: never as HTML. */
  render: (row: T) => ReactNode;
  /** Present => the column is sortable. */
  sortValue?: (row: T) => SortValue;
  numeric?: boolean;
  /** Text for assistive tech when `header` is an icon. */
  headerLabel?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export function compareValues(a: SortValue, b: SortValue, dir: "asc" | "desc"): number {
  const an = a == null || (typeof a === "number" && Number.isNaN(a));
  const bn = b == null || (typeof b === "number" && Number.isNaN(b));
  if (an || bn) return an && bn ? 0 : an ? 1 : -1; // empty values always last
  const c =
    typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return dir === "asc" ? c : -c;
}

export function sortRows<T>(rows: T[], columns: Column<T>[], sort: SortState | null): T[] {
  const col = sort && columns.find((c) => c.key === sort.key);
  if (!sort || !col?.sortValue) return rows;
  const sv = col.sortValue;
  return rows
    .map((r, i) => [r, i] as const)
    .sort((x, y) => compareValues(sv(x[0]), sv(y[0]), sort.dir) || x[1] - y[1])
    .map(([r]) => r);
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  sort: sortProp,
  onSortChange,
  defaultSort = null,
  rowClassName,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Required for accessibility; visually hidden. */
  caption: string;
  sort?: SortState | null;
  onSortChange?: (s: SortState | null) => void;
  defaultSort?: SortState | null;
  rowClassName?: (row: T) => string | undefined;
}) {
  const [inner, setInner] = useState<SortState | null>(defaultSort);
  const controlled = sortProp !== undefined;
  const sort = controlled ? sortProp : inner;
  const setSort = (s: SortState | null) => (controlled ? onSortChange?.(s) : (setInner(s), onSortChange?.(s)));
  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);

  const toggle = (key: string) => {
    if (sort?.key !== key) setSort({ key, dir: "asc" });
    else if (sort.dir === "asc") setSort({ key, dir: "desc" });
    else setSort(null);
  };

  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key ? sort : null;
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={c.numeric ? "num" : undefined}
                  aria-sort={active ? (active.dir === "asc" ? "ascending" : "descending") : c.sortValue ? "none" : undefined}
                >
                  {c.sortValue ? (
                    <button type="button" className="th-btn" onClick={() => toggle(c.key)} aria-label={`Sort by ${c.headerLabel ?? (typeof c.header === "string" ? c.header : c.key)}`}>
                      {c.header}
                      <span className="th-arrow" aria-hidden="true">
                        {active ? (active.dir === "asc" ? "▲" : "▼") : ""}
                      </span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className={rowClassName?.(row)}>
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? "num" : undefined}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
