import { useSyncExternalStore, type ReactNode } from "react";
import { authState, getToken } from "../api";

export function AccessDenied() {
  return (
    <main className="denied" aria-labelledby="denied-title">
      <div className="denied-card">
        <h1 id="denied-title">Open the URL printed by lrae ui</h1>
        <p>
          This page needs the access token that <code>lrae ui</code> creates each time it starts. The server rejected the request, or no token was
          given.
        </p>
        <ol>
          <li>
            Look in the terminal where you ran <code>lrae ui</code>.
          </li>
          <li>
            Open the line that looks like <code>http://127.0.0.1:8765/#token=&hellip;</code> (or start it with <code>--open</code>).
          </li>
        </ol>
        <p className="muted">The token changes on every start, so a bookmark from an earlier session will not work.</p>
      </div>
    </main>
  );
}

/** Shows the "open the printed URL" screen when there is no token or any request got a 401. */
export function AuthGate({ children }: { children: ReactNode }) {
  const denied = useSyncExternalStore(authState.subscribe, authState.isDenied);
  if (denied || !getToken()) return <AccessDenied />;
  return <>{children}</>;
}
