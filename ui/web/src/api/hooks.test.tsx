import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataVersionProvider, useDataVersion } from "../app/DataVersion";
import { useAsync } from "./hooks";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe("useAsync and the data version", () => {
  it("keeps the data on screen while a new store version re-fetches; a deps change clears it", async () => {
    const answers: ReturnType<typeof deferred<string>>[] = [];
    let bump = () => {};
    function View({ id }: { id: string }) {
      bump = useDataVersion().bump;
      const q = useAsync(() => {
        const d = deferred<string>();
        answers.push(d);
        return d.promise;
      }, [id]);
      return <div>{q.loading ? "loading" : q.data}</div>;
    }
    const { rerender } = render(<DataVersionProvider><View id="a" /></DataVersionProvider>);
    expect(screen.getByText("loading")).toBeInTheDocument();
    await act(async () => answers[0].resolve("first"));
    expect(screen.getByText("first")).toBeInTheDocument();

    act(() => bump());                                   // an ingest finished
    expect(answers).toHaveLength(2);
    expect(screen.getByText("first")).toBeInTheDocument(); // no spinner, no blank page
    await act(async () => answers[1].resolve("second"));
    expect(screen.getByText("second")).toBeInTheDocument();

    rerender(<DataVersionProvider><View id="b" /></DataVersionProvider>);
    expect(screen.getByText("loading")).toBeInTheDocument(); // another run: old data must not show
  });
});
