import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// StrictMode temporarily disabled: double-invocation of effects was racing
// keycloak-js nonce storage and causing redirect loop after SSO callback.
createRoot(document.getElementById("root")!).render(<App />);
