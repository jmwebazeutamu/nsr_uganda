import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// US-S22-003c — JS test runner for design/v0.1/components/*.test.jsx.
// The browser harness still loads the components via Babel-standalone;
// these tests render them via React + RTL in a jsdom environment,
// with primitives (Icon, Chip, Modal) stubbed in vitest.setup.js so
// the component-under-test can resolve them as globals exactly the
// way the browser does.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.js"],
    include: ["design/**/*.test.{js,jsx}"],
    // The components reference React + primitives via top-level
    // identifiers (no ES imports). The setup file binds those on
    // globalThis before the test files evaluate.
  },
});
