import { ReactNode, useEffect, useState } from "react";

// Tiny hash router: "#/farms/3?x=1". Keeps the app a plain static site (no server rewrite rules needed).
export function usePath(): string {
  const read = () => (window.location.hash.slice(1).split("?")[0] || "/");
  const [p, setP] = useState(read());
  useEffect(() => { const f = () => setP(read()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  return p;
}
export const go = (to: string) => { window.location.hash = to; };
export function Link({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  return <a href={"#" + to} className={className}>{children}</a>;
}
export function match(path: string, pattern: string): Record<string, string> | null {
  const a = path.split("/").filter(Boolean), b = pattern.split("/").filter(Boolean);
  if (a.length !== b.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < b.length; i++) {
    if (b[i].startsWith(":")) params[b[i].slice(1)] = decodeURIComponent(a[i]);
    else if (a[i] !== b[i]) return null;
  }
  return params;
}
