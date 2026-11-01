import { ReactNode, useCallback, useEffect, useState } from "react";
import { errText } from "./api";

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn().then((d) => { setData(d); setError(""); }).catch((e) => setError(errText(e))).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

export function Msg({ kind = "err", children }: { kind?: "err" | "ok" | "info"; children?: ReactNode }) {
  return children ? <div className={"msg " + kind} role={kind === "err" ? "alert" : "status"}>{children}</div> : null;
}

export function Loading({ loading, error, children }: { loading: boolean; error: string; children: ReactNode }) {
  if (loading) return <p className="muted">Loading...</p>;
  if (error) return <Msg>{error}</Msg>;
  return <>{children}</>;
}

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return <section className="card">{(title || right) && <div className="row"><h3 className="grow" style={{ margin: 0 }}>{title}</h3>{right}</div>}{children}</section>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label>{label}{children}</label>;
}

type Col<R> = { head: string; cell: (r: R) => ReactNode };
export function Table<R>({ rows, cols, empty = "Nothing here yet." }: { rows: R[]; cols: Col<R>[]; empty?: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <div className="scroll"><table><thead><tr>{cols.map((c) => <th key={c.head}>{c.head}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c.head}>{c.cell(r)}</td>)}</tr>)}</tbody></table></div>
  );
}

const TONE: Record<string, string> = { ACTIVE: "good", DELIVERED: "good", APPROVED: "good", VERIFIED: "good", ONLINE: "good", COMPLETED: "good", PAID: "good", RESOLVED: "good", REPORT_READY: "good", CONFIRMED: "good", ACCEPTED: "good",
  PENDING: "warn", PENDING_APPROVAL: "warn", PENDING_VERIFICATION: "warn", REQUESTED: "warn", PLACED: "warn", OPEN: "warn", OFFLINE: "bad", WARN: "warn",
  CANCELLED: "bad", REJECTED: "bad", BLOCKED: "bad", SUSPENDED: "bad", FAULT: "bad", FAILED: "bad", DECLINED: "bad" };
export function Tag({ v }: { v: string }) { return <span className={"tag " + (TONE[v] || "")}>{v.replace(/_/g, " ").toLowerCase()}</span>; }

/** Run an async action, show its error or success text, and reload afterwards. */
export function useAction(after?: () => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const run = async (fn: () => Promise<unknown>, okText = "") => {
    setBusy(true); setErr(""); setOk("");
    try { await fn(); setOk(okText); after?.(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  return { run, busy, err, ok, box: <><Msg>{err}</Msg><Msg kind="ok">{ok}</Msg></> };
}

export function Sparkline({ points, width = 280, height = 60 }: { points: number[]; width?: number; height?: number }) {
  if (points.length < 2) return <span className="muted">Not enough data</span>;
  const lo = Math.min(...points), hi = Math.max(...points), span = hi - lo || 1;
  const d = points.map((v, i) => `${i ? "L" : "M"}${(i / (points.length - 1)) * width},${height - ((v - lo) / span) * (height - 6) - 3}`).join(" ");
  return <svg width={width} height={height} role="img" aria-label="trend"><path d={d} fill="none" stroke="#2f6b3a" strokeWidth="2" /></svg>;
}

export const val = (e: { target: { value: string } }) => e.target.value;
export const num = (s: string) => (s === "" ? undefined : Number(s));
