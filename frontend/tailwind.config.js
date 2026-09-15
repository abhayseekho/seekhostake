/** Dark sportsbook palette (Stake-ish): deep slate surfaces, green/red accents per swimmer. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0f1923",
        card: "#1a2732",
        edge: "#263441",
        ink: "#e6edf3",
        dim: "#8fa3b0",
        khuseel: "#22c55e",
        bansod: "#38bdf8",
        gold: "#fbbf24",
        bad: "#f87171",
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
};
