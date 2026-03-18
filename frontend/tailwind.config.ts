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
        clr: {
          action: '#0079b8',
          'action-hover': '#004a7c',
          'action-light': '#49afd9',
        },
        'clr-header': '#314351',
        'clr-near-white': '#fafafa',
        'clr-light-gray': '#f2f2f2',
        'clr-border': '#d7d7d7',
        'clr-placeholder': '#9a9a9a',
        'clr-text-secondary': '#565656',
        'clr-text': '#313131',
        'clr-success': '#62a420',
        'clr-danger': '#c92100',
        'clr-warning': '#c25400',
        terminal: '#0d1117',
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
