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

        // Surfaces. A card on white needs to read as a distinct plane
        // without a hard 1px rule fighting every other rule on screen.
        'clr-surface': '#ffffff',
        'clr-surface-sunken': '#f7f8f9',
        'clr-border-subtle': '#e6e8ea',

        // Status tints, so callouts stop reaching into the raw Tailwind
        // palette and drifting apart page by page.
        'clr-success-bg': '#f0f8e6',
        'clr-success-text': '#3d6b0f',
        'clr-warning-bg': '#fdf3e7',
        'clr-warning-text': '#8a3d00',
        'clr-danger-bg': '#fdeceb',
        'clr-danger-text': '#8f1800',
        'clr-info-bg': '#e8f4fa',
        'clr-info-text': '#00506d',
      },
      borderRadius: {
        // Clarity's 2px reads as unfinished at this density; controls get
        // 4px and containers 8px so the two are distinguishable.
        DEFAULT: '0.25rem',
        card: '0.5rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(16 24 40 / 0.04), 0 1px 3px 0 rgb(16 24 40 / 0.06)',
        'card-hover': '0 2px 4px -1px rgb(16 24 40 / 0.06), 0 4px 8px -2px rgb(16 24 40 / 0.08)',
      },
      fontSize: {
        // A page title at 18px next to 14px body gives no hierarchy.
        'page-title': ['1.375rem', { lineHeight: '1.75rem', letterSpacing: '-0.01em', fontWeight: '600' }],
        'section-title': ['0.9375rem', { lineHeight: '1.375rem', fontWeight: '600' }],
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
