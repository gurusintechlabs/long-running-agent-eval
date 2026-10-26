// Incremental parser for the text/event-stream wire format (WHATWG "Server-sent events" section 9.2).
// It works on decoded text chunks of any size: a frame may be split anywhere, several frames may share a
// chunk, and CR, LF and CRLF line ends are all accepted. Field values are plain strings; this module never
// interprets them (no HTML, no eval), the caller JSON-parses `data`.

export interface RawFrame {
  event: string;
  id: string | null;
  data: string;
  retry: number | null;
}

export class SseParser {
  private buf = "";
  private event = "";
  private data: string[] = [];
  private hasData = false;
  private id: string | null = null;
  private retry: number | null = null;
  private first = true;

  /** Feed one decoded chunk; returns the frames completed by it. */
  push(chunk: string): RawFrame[] {
    if (this.first) {
      this.first = false;
      if (chunk.charCodeAt(0) === 0xfeff) chunk = chunk.slice(1); // BOM
    }
    this.buf += chunk;
    const out: RawFrame[] = [];
    let start = 0;
    const b = this.buf;
    for (let i = 0; i < b.length; i++) {
      const c = b.charCodeAt(i);
      if (c !== 10 && c !== 13) continue;
      if (c === 13 && i === b.length - 1) break; // a CR at the very end may be half of a CRLF: wait
      const line = b.slice(start, i);
      if (c === 13 && b.charCodeAt(i + 1) === 10) i++;
      start = i + 1;
      const f = this.line(line);
      if (f) out.push(f);
    }
    this.buf = b.slice(start);
    return out;
  }

  private line(line: string): RawFrame | null {
    if (line === "") {
      // blank line: dispatch
      const had = this.hasData;
      const frame: RawFrame = { event: this.event || "message", id: this.id, data: this.data.join("\n"), retry: this.retry };
      this.event = "";
      this.data = [];
      this.hasData = false;
      this.retry = null;
      // `id` persists across frames per the spec, but our server sends one per frame; keep it simple and reset.
      this.id = null;
      return had ? frame : null;
    }
    if (line.charCodeAt(0) === 58) return null; // ":" comment
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.charCodeAt(0) === 32) value = value.slice(1);
    switch (field) {
      case "event":
        this.event = value;
        break;
      case "data":
        this.data.push(value);
        this.hasData = true;
        break;
      case "id":
        if (!value.includes("\0")) this.id = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) this.retry = Number(value);
        break;
      default:
        break;
    }
    return null;
  }
}
