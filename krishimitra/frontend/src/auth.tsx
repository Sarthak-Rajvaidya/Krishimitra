import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

export interface Me {
  id: number; full_name: string; role: string; status: string; permissions: string[]; language: string; portal: string;
  mobile?: string; email?: string; district_id?: number | null;
}
interface Ctx { me: Me | null; loading: boolean; setMe: (m: Me | null) => void; logout: () => Promise<void> }
const C = createContext<Ctx>(null as never);
export const useAuth = () => useContext(C);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => { api.get<Me>("/auth/me").then(setMe).catch(() => setMe(null)).finally(() => setLoading(false)); }, []);
  const logout = useCallback(async () => { try { await api.post("/auth/logout"); } catch { /* already signed out */ } setMe(null); window.location.hash = "/"; }, []);
  return <C.Provider value={{ me, loading, setMe, logout }}>{children}</C.Provider>;
}
// UI convenience only. The API checks every permission again on every request.
export const can = (me: Me | null, p: string) => !!me?.permissions.includes(p);
