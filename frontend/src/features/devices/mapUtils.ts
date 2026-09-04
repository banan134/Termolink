export const STATUS_COLOR: Record<string, string> = { online: "#1a7f37", offline: "#b91c1c", error: "#b91c1c", rate_limited: "#b45309", unknown: "#6b7280" };
export const DEFAULT_CENTER: [number, number] = [53.78, 20.49]; // Olsztyn

export function escapeHtml(v: string): string {
  return v.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}
