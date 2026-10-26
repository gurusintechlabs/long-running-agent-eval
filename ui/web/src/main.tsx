import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { initToken } from "./api";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";

// Read the token from the URL fragment and strip it from the address bar before anything renders.
initToken();

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
