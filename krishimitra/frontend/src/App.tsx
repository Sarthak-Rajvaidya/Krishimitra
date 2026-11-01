import { useEffect, useState } from "react";
import { api } from "./api";
import { AuthProvider, useAuth } from "./auth";
import { LANGS, getLang, onLang, setLang, t } from "./i18n";
import Auth from "./pages/Auth";
import { Assistant, Doctor } from "./pages/AiPages";
import { Farms, Crops, Home, Soil } from "./pages/FarmPages";
import { Alerts, Community, Devices, Experts, Learn, Machines, MyMachines, Settings, Support, Wallet } from "./pages/MorePages";
import { Admin, Delivery, Executive, ExpertPortal, SoilCenterPortal, Supplier } from "./pages/Portals";
import { Cart, Orders, Shop, Suppliers, Wishlist } from "./pages/ShopPages";
import { Link, usePath } from "./router";
import { Msg } from "./ui";

const FARMER_NAV: [string, string][] = [["/", "nav.home"], ["/farms", "nav.farms"], ["/crops", "nav.crops"], ["/soil", "nav.soil"], ["/doctor", "nav.doctor"], ["/assistant", "nav.assistant"], ["/market", "nav.market"],
  ["/orders", "nav.orders"], ["/machines", "nav.machines"], ["/devices", "nav.devices"], ["/experts", "nav.experts"], ["/community", "nav.community"], ["/learn", "nav.learn"], ["/schemes", "nav.schemes"], ["/wallet", "nav.wallet"], ["/support", "nav.support"]];
const PORTAL_NAV: Record<string, [string, string][]> = {
  EXPERT: [["/expert", "Dashboard"], ["/community", "nav.community"], ["/wallet", "nav.wallet"], ["/support", "nav.support"]], SUPPLIER: [["/supplier", "Dashboard"], ["/wallet", "nav.wallet"], ["/support", "nav.support"]],
  DELIVERY: [["/delivery", "Deliveries"], ["/wallet", "nav.wallet"], ["/support", "nav.support"]], SOIL_CENTER: [["/soil-center", "Requests"], ["/support", "nav.support"]],
  DISTRICT_MANAGER: [["/district", "District"]], ADMIN: [["/admin", "Admin"]], SUPER_ADMIN: [["/admin", "Admin"]], FINANCE: [["/finance", "Finance"]], DEVELOPER: [["/developer", "System"]], FOUNDER: [["/founder", "Overview"]],
};

function Shell() {
  const { me, loading, logout } = useAuth();
  const path = usePath();
  const [, force] = useState(0);
  const [unread, setUnread] = useState(0);
  useEffect(() => onLang(() => force((n) => n + 1)), []);
  useEffect(() => { if (me) { const f = () => api.get("/notifications/count").then((r) => setUnread(r.unread)).catch(() => {}); f(); const i = setInterval(f, 60000); return () => clearInterval(i); } }, [me, path]);
  if (loading) return <main><p className="muted">{t("common.loading")}</p></main>;
  const lang = <select aria-label={t("common.language")} value={getLang()} onChange={(e) => setLang(e.target.value as any)}>{LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}</select>;
  if (!me) return <><header className="top"><a className="brand" href="#/">KrishiMitra</a>{lang}</header><main><Auth /></main></>;
  const farmer = me.role === "FARMER";
  const nav = farmer ? FARMER_NAV : PORTAL_NAV[me.role] || [];
  const label = (s: string) => (s.includes(".") ? t(s) : s);
  const home = farmer ? "/" : nav[0][0];
  const p = path === "/" && !farmer ? home : path;
  const first = "/" + (p.split("/")[1] || "");
  let page;
  if (me.status === "PENDING_APPROVAL") page = <><h1>Waiting for approval</h1><Msg kind="info">Your account is being reviewed. You can upload verification documents in Settings. We will notify you when it is approved.</Msg></>;
  else if (farmer) page = (
    first === "/" ? <Home me={me} /> : first === "/farms" ? <Farms path={p} /> : first === "/crops" ? <Crops path={p} /> : first === "/soil" ? <Soil /> : first === "/doctor" ? <Doctor /> : first === "/assistant" ? <Assistant /> :
    first === "/market" ? <Shop path={p} /> : first === "/cart" ? <Cart /> : first === "/wishlist" ? <Wishlist /> : first === "/suppliers" ? <Suppliers /> : first === "/orders" ? <Orders /> :
    p === "/machines/mine" ? <MyMachines /> : first === "/machines" ? <Machines /> : first === "/devices" ? <Devices path={p} /> : first === "/experts" ? <Experts /> : first === "/community" ? <Community /> :
    first === "/learn" ? <Learn /> : first === "/schemes" ? <Learn schemes /> : first === "/wallet" ? <Wallet /> : first === "/support" ? <Support /> : first === "/alerts" ? <Alerts /> : first === "/settings" ? <Settings me={me} /> : <h1>Page not found</h1>);
  else page = (
    first === "/expert" ? <ExpertPortal /> : first === "/supplier" ? <Supplier /> : first === "/delivery" ? <Delivery /> : first === "/soil-center" ? <SoilCenterPortal /> : ["/admin", "/district"].includes(first) ? <Admin me={me} /> :
    ["/finance", "/developer", "/founder"].includes(first) ? <Executive me={me} /> : first === "/wallet" ? <Wallet /> : first === "/support" ? <Support /> : first === "/community" ? <Community /> : first === "/alerts" ? <Alerts /> : first === "/settings" ? <Settings me={me} /> : <h1>Page not found</h1>);
  return <>
    <header className="top"><a className="brand" href={"#" + home}>KrishiMitra</a>{lang}
      <Link to="/alerts" className="btn">🔔 {unread > 0 ? unread : ""}</Link><Link to="/settings" className="btn">{me.full_name.split(" ")[0]}</Link><button onClick={logout}>{t("common.logout")}</button></header>
    <nav className="menu" aria-label="Main">{nav.map(([to, l]) => <Link key={to} to={to} className={(to === "/" ? p === "/" : p.startsWith(to)) ? "on" : ""}>{label(l)}</Link>)}</nav>
    <main>{page}</main></>;
}

export default function App() { return <AuthProvider><Shell /></AuthProvider>; }
