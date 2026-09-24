/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // Design tokens, straight from design-reference.html's :root block.
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        line: "var(--line)",
        "line-2": "var(--line-2)",
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        panel: "var(--panel)",
        accent: "var(--accent)",
        "accent-bg": "var(--accent-bg)",
        ok: "var(--ok)",
        "ok-bg": "var(--ok-bg)",
        err: "var(--err)",
        "err-bg": "var(--err-bg)",
        run: "var(--run)",
        "run-bg": "var(--run-bg)",
        trigger: "var(--t-trigger)",
        flow: "var(--t-flow)",
        data: "var(--t-data)",
        action: "var(--t-action)",

        // shadcn/ui theme variables, pointed at the same tokens.
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: { DEFAULT: "var(--card)", foreground: "var(--card-foreground)" },
        popover: { DEFAULT: "var(--popover)", foreground: "var(--popover-foreground)" },
        primary: { DEFAULT: "var(--primary)", foreground: "var(--primary-foreground)" },
        secondary: { DEFAULT: "var(--secondary)", foreground: "var(--secondary-foreground)" },
        muted: { DEFAULT: "var(--muted)", foreground: "var(--muted-foreground)" },
        destructive: { DEFAULT: "var(--destructive)", foreground: "var(--destructive-foreground)" },
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "pulse-run": {
          "50%": { boxShadow: "0 0 0 5px rgba(217,154,14,.18)" },
        },
      },
      animation: {
        "pulse-run": "pulse-run 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
