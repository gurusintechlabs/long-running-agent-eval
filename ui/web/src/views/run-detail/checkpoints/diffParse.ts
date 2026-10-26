export type LineKind = "add" | "del" | "ctx" | "hunk" | "meta";

export interface DiffLine {
  kind: LineKind;
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

export interface DiffFile {
  path: string;
  lines: DiffLine[];
  added: number;
  deleted: number;
  binary: boolean;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function pathOf(header: string): string {
  // "diff --git a/x b/y" -> y (best effort; the file list from the API is authoritative)
  const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(header);
  return m ? m[2] : header.replace(/^diff --git /, "");
}

/** Parse a unified diff into per-file line records with old/new line numbers. Pure text handling, no HTML. */
export function parseDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  if (!diff) return files;
  let cur: DiffFile | null = null;
  let inHunk = false;
  let o = 0;
  let n = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("diff --git ")) {
      cur = { path: pathOf(line), lines: [], added: 0, deleted: 0, binary: false };
      files.push(cur);
      cur.lines.push({ kind: "meta", text: line, oldNo: null, newNo: null });
      inHunk = false;
      continue;
    }
    if (!cur) {
      cur = { path: "(diff)", lines: [], added: 0, deleted: 0, binary: false };
      files.push(cur);
    }
    const h = HUNK.exec(line);
    if (h) {
      inHunk = true;
      o = Number(h[1]);
      n = Number(h[2]);
      cur.lines.push({ kind: "hunk", text: line, oldNo: null, newNo: null });
      continue;
    }
    if (!inHunk) {
      if (line.startsWith("Binary files")) cur.binary = true;
      if (line !== "") cur.lines.push({ kind: "meta", text: line, oldNo: null, newNo: null });
      continue;
    }
    if (line.startsWith("+")) {
      cur.added++;
      cur.lines.push({ kind: "add", text: line.slice(1), oldNo: null, newNo: n++ });
    } else if (line.startsWith("-")) {
      cur.deleted++;
      cur.lines.push({ kind: "del", text: line.slice(1), oldNo: o++, newNo: null });
    } else if (line.startsWith("\\")) {
      cur.lines.push({ kind: "meta", text: line, oldNo: null, newNo: null });
    } else if (line.startsWith(" ")) {
      cur.lines.push({ kind: "ctx", text: line.slice(1), oldNo: o++, newNo: n++ });
    }
  }
  return files;
}
