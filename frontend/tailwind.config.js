/** SeekhoStake palette — Stake-inspired deep blue-slate, per approved prototype. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e1621",
        card: "#17222e",     // surface
        raise: "#1e2b3a",
        edge: "#26344a",
        ink: "#eaf1f7",
        dim: "#8fa2b3",
        faint: "#5c6d7d",
        khuseel: "#21c065",
        bansod: "#3aa8f0",
        gold: "#f2b83b",
        bad: "#f56262",
      },
      fontFamily: { sans: ["-apple-system", "SF Pro Text", "Segoe UI", "system-ui", "sans-serif"] },
      keyframes: {
        flashup: { "0%": { backgroundColor: "rgba(33,192,101,.25)" }, "100%": { backgroundColor: "#17222e" } },
        flashdn: { "0%": { backgroundColor: "rgba(245,98,98,.25)" }, "100%": { backgroundColor: "#17222e" } },
      },
      animation: { flashup: "flashup .9s", flashdn: "flashdn .9s" },
    },
  },
  plugins: [],
};
