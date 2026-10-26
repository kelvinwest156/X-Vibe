import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Manrope", "system-ui", "sans-serif"],
      },
      colors: {
        ink: { DEFAULT: "#252423", 2: "#605e5c", 3: "#8a8886" },
        canvas: "#f3f2f1",
        line: { DEFAULT: "#e1dfdd", soft: "#edebe9" },
        pbi: {
          yellow: "#f2c811",
          teal: "#01b8aa",
          slate: "#374649",
          coral: "#fd625e",
          sky: "#8ad4eb",
          orange: "#fe9666",
          plum: "#a66999",
        },
      },
    },
  },
  plugins: [],
};

export default config;
