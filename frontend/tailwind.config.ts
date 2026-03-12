import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      colors: {
        surface: {
          DEFAULT: "rgb(2 6 23)",       // slate-950
          raised: "rgb(15 23 42)",      // slate-900
          overlay: "rgb(30 41 59 / 0.5)", // slate-800/50
        },
        border: {
          DEFAULT: "rgb(51 65 85)",     // slate-700
          subtle: "rgb(51 65 85 / 0.5)", // slate-700/50
          muted: "rgb(30 41 59)",       // slate-800
        },
        terminal: "#0d1117",
      },
      height: {
        topbar: "3.5rem",    // h-14
        terminal: "16rem",   // h-64
      },
      width: {
        sidebar: "24rem",    // w-96
      },
    },
  },
  plugins: [],
};

export default config;
