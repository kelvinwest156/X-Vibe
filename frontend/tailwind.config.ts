import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Outfit", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      colors: {
        bi: {
          canvas: "#0B0F19",
          sidebar: "#0F1524",
          card: "#141C2F",
          cardHover: "#19233B",
          input: "#0D1322",
          border: "#222E4A",
          cyan: "#38BDF8",
          purple: "#A78BFA",
          emerald: "#34D399",
          amber: "#FBBF24",
          rose: "#F87171",
        },
      },
    },
  },
  plugins: [],
};

export default config;
