import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "./App";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("login screen renders with e-mail and password fields", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "not_authenticated", message: "" } }), {
      status: 403,
    }),
  );
  renderAt("/login");
  expect(await screen.findByRole("heading", { name: "Zaloguj się" }, { timeout: 5000 })).toBeInTheDocument();
  expect(screen.getByLabelText("E-mail")).toBeInTheDocument();
  expect(screen.getByLabelText("Hasło")).toBeInTheDocument();
});

test("protected route redirects to login when not authenticated", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "not_authenticated", message: "" } }), {
      status: 403,
    }),
  );
  renderAt("/account");
  expect(await screen.findByRole("heading", { name: "Zaloguj się" }, { timeout: 5000 })).toBeInTheDocument();
});
