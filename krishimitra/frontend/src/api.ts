// Every call goes to /api/v1 using an httpOnly session cookie. There are no keys or secrets in the frontend.
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const res = await fetch(BASE + path, {
    method, credentials: "include",
    // X-KM-Client is required by the API for cookie sessions (cross-site request protection)
    headers: { "X-KM-Client": "web", ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}), ...headers },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, msg);
  }
  const type = res.headers.get("content-type") || "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b: unknown = {}, h?: Record<string, string>) => request<T>("POST", p, b, h),
  put: <T = any>(p: string, b: unknown = {}) => request<T>("PUT", p, b),
  patch: <T = any>(p: string, b: unknown = {}) => request<T>("PATCH", p, b),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  upload: <T = any>(p: string, f: FormData) => request<T>("POST", p, f),
};

export const rupees = (paise: number | null | undefined) =>
  paise == null ? "-" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(paise / 100);

export const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "-");
export const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { dateStyle: "medium" }) : "-");
export const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
