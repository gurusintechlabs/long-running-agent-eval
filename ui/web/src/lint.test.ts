// UI-5 guard: the ESLint config must reject every raw-HTML sink, and the shipped source must not use any.
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: process.cwd() });

async function messages(code: string) {
  const [r] = await eslint.lintText(code, { filePath: "src/probe.tsx" });
  return r.messages.map((m) => m.message);
}

describe("raw HTML is banned (UI-5)", () => {
  it.each([
    ["dangerouslySetInnerHTML", 'export const A = (p: {h: string}) => <div dangerouslySetInnerHTML={{ __html: p.h }} />;'],
    ["innerHTML", "export const f = (e: HTMLElement, h: string) => { e.innerHTML = h; };"],
    ["outerHTML", "export const f = (e: HTMLElement, h: string) => { e.outerHTML = h; };"],
    ["insertAdjacentHTML", "export const f = (e: HTMLElement, h: string) => { e.insertAdjacentHTML('beforeend', h); };"],
    ["document.write", "export const f = (h: string) => { document.write(h); };"],
    ["eval", "export const f = (h: string) => eval(h);"],
  ])("flags %s", async (_n, code) => {
    const msgs = await messages(code);
    expect(msgs.some((m) => m.startsWith("UI-5"))).toBe(true);
  });

  it("accepts ordinary JSX", async () => {
    expect(await messages("export const A = ({t}: {t: string}) => <p>{t}</p>;")).toEqual([]);
  });
});
