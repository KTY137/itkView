// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-7feb6f371123
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initializeAppearance } from "./appearance";
import { AuthProvider } from "./auth";
import { product, setProductDocumentTitle } from "./product";
import "./app.css";

setProductDocumentTitle(product, document);
initializeAppearance();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
);
