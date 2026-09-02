import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError } from "@/api/client";
import { authApi, type Me, type UiTheme } from "@/api/auth";

export const ME_KEY = ["me"] as const;

/** Current user; `null` when not authenticated (401/403 are not errors here). */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await authApi.me();
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
        throw err;
      }
    },
    staleTime: 30_000,
    retry: false,
  });
}

export function applyTheme(theme: UiTheme | null | undefined) {
  const root = document.documentElement;
  if (theme === "dark") root.setAttribute("data-theme", "dark");
  else root.removeAttribute("data-theme"); // light is the default, ignoring OS preference (docs/09)
}

/** Keeps <html data-theme> in sync with the profile; light before login. */
export function useThemeSync(me: Me | null | undefined) {
  useEffect(() => {
    applyTheme(me?.ui_theme ?? "light");
  }, [me?.ui_theme]);
}

export function useSetTheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ui_theme: UiTheme) => authApi.patchMe({ ui_theme }),
    onMutate: (ui_theme) => applyTheme(ui_theme), // optimistic
    onSuccess: (me) => qc.setQueryData(ME_KEY, me),
    onError: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => {
      qc.setQueryData(ME_KEY, null);
      qc.clear();
      qc.setQueryData(ME_KEY, null);
    },
  });
}
