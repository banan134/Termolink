import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, csrfToken } from "./client";

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends JSON with the CSRF header on mutations", async () => {
    document.cookie = "csrftoken=abc123";
    expect(csrfToken()).toBe("abc123");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const result = await api<{ ok: boolean }>("/auth/login", {
      method: "POST",
      body: { email: "a@b.c" },
    });
    expect(result).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBe("abc123");
    expect(init?.credentials).toBe("same-origin");
  });

  it("turns the error envelope into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: "login_locked", message: "Zablokowane", fields: {}, retry_after_s: 42 },
        }),
        { status: 429 },
      ),
    );
    await expect(api("/auth/login", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 429,
      code: "login_locked",
      retryAfterS: 42,
      message: "Zablokowane",
    });
  });

  it("returns undefined for 204 and maps network failures", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(await api("/auth/logout", { method: "POST" })).toBeUndefined();
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("offline"));
    const err = await api("/auth/me").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network");
  });
});
