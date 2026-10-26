// The per-start token arrives in the URL fragment (`#token=...`), which browsers never send to the server.
// We read it once, keep it in memory and sessionStorage (so a reload keeps working), and strip it from
// the address bar. It is never written to localStorage.

const STORAGE_KEY = "lrae.token";
let memoryToken: string | null = null;

function safeSession(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function parseFragmentToken(hash: string): string | null {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const t = params.get("token");
  return t && t.length > 0 ? t : null;
}

/** Call once at startup, before the first render. Returns the token in use, if any. */
export function initToken(): string | null {
  const fromHash = parseFragmentToken(window.location.hash);
  if (fromHash) {
    memoryToken = fromHash;
    try {
      safeSession()?.setItem(STORAGE_KEY, fromHash);
    } catch {
      /* storage may be blocked: memory still works for this page load */
    }
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
    return memoryToken;
  }
  if (memoryToken) return memoryToken;
  try {
    memoryToken = safeSession()?.getItem(STORAGE_KEY) ?? null;
  } catch {
    memoryToken = null;
  }
  return memoryToken;
}

export function getToken(): string | null {
  return memoryToken;
}

export function clearToken(): void {
  memoryToken = null;
  try {
    safeSession()?.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/** Test helper. */
export function _resetTokenForTests(): void {
  memoryToken = null;
}
