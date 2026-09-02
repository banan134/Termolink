import "@testing-library/jest-dom/vitest";

// fetch is not available in jsdom; components under test must not depend on a live API.
if (typeof globalThis.fetch !== "function") {
  globalThis.fetch = (() => Promise.reject(new Error("fetch not available in tests"))) as typeof fetch;
}
