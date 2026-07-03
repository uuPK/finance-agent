import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172033",
        muted: "#667085",
        line: "#d9dee8",
        surface: "#f7f8fb",
        accent: "#0f766e"
      }
    }
  },
  plugins: []
} satisfies Config;
