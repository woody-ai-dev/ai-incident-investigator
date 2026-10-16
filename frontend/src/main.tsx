import { setNonce } from "get-nonce";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// Nginx replaces this placeholder with the per-response style nonce.
// Local Vite development has no CSP and leaves the placeholder unchanged.
const nonce = document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content;
if (nonce && /^[a-f0-9]{32}$/.test(nonce)) setNonce(nonce);

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
