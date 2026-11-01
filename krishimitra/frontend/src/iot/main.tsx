import { useState } from "react";
import { createRoot } from "react-dom/client";
import { api, when } from "../api";
import { AuthProvider, useAuth } from "../auth";
import { Chart } from "../pages/MorePages";
import Auth from "../pages/Auth";
import { Card, Loading, Msg, Tag, useAction, useLoad } from "../ui";
import "../styles.css";

const METRICS: [string, string][] = [["soil_moisture", "Soil moisture %"], ["temperature", "Temperature °C"], ["humidity", "Humidity %"], ["water_level", "Tank level %"], ["rainfall", "Rain mm"]];

function Detail({ id }: { id: number }) {
  const [metric, setMetric] = useState("soil_moisture");
  const [hours, setHours] = useState(24);
  const hist = useLoad(() => api.get(`/iot/devices/${id}/history?metric=${metric}&hours=${hours}`), [id, metric, hours]);
  const irr = useLoad(() => api.get(`/iot/devices/${id}/irrigation`).catch(() => null), [id]);
  const a = useAction(() => irr.reload());
  return <>
    <Card title="History">
      <div className="row">
        <select aria-label="Metric" value={metric} onChange={(e) => setMetric(e.target.value)}>{METRICS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <select aria-label="Period" value={hours} onChange={(e) => setHours(Number(e.target.value))}><option value={6}>6 hours</option><option value={24}>24 hours</option><option value={168}>7 days</option><option value={720}>30 days</option></select>
      </div>
      <Loading loading={hist.loading} error={hist.error}>{hist.data && <Chart points={hist.data.points.map((p: any) => p.v)} />}</Loading>
    </Card>
    {irr.data?.config && <Card title="Irrigation" right={<Tag v={irr.data.pump_running ? "ON" : "OFF"} />}>
      <p className="muted">Mode: {irr.data.config.mode.toLowerCase()} · start below {irr.data.config.moisture_low}% · stop above {irr.data.config.moisture_high}% · max {irr.data.config.max_minutes} min</p>
      <div className="row">
        <button disabled={a.busy} onClick={() => a.run(() => api.post(`/iot/devices/${id}/pump`, { action: "ON", minutes: 15 }), "Command sent. The pump starts when the device next checks in.")}>Pump on (15 min)</button>
        <button className="alt" disabled={a.busy} onClick={() => a.run(() => api.post(`/iot/devices/${id}/pump`, { action: "OFF" }), "Stop command sent")}>Pump off</button>
      </div>{a.box}
      <p className="muted">Manual commands pause automatic irrigation for 1 hour. Change rules in the main KrishiMitra app.</p>
      <table><thead><tr><th>Started</th><th>Minutes</th><th>By</th></tr></thead><tbody>{irr.data.history.map((r: any, i: number) => <tr key={i}><td>{when(r.started_at)}</td><td>{r.minutes ?? "running"}</td><td>{r.source}</td></tr>)}</tbody></table>
    </Card>}
  </>;
}

function Monitor() {
  const { me, loading, logout } = useAuth();
  const devs = useLoad(() => api.get<any[]>("/iot/devices").catch(() => []), [me?.id]);
  const [sel, setSel] = useState<number | null>(null);
  if (loading) return <main><p className="muted">Loading…</p></main>;
  if (!me) return <><header className="top"><span className="brand">KrishiMitra IoT</span></header><main><Auth /></main></>;
  const cur = (devs.data || []).find((d) => d.id === (sel ?? devs.data?.[0]?.id));
  return <>
    <header className="top"><span className="brand">KrishiMitra IoT</span><a className="btn" href="/">Main app</a><button onClick={logout}>Log out</button></header>
    <main>
      <h1>Device monitor</h1>
      {me.role !== "FARMER" && <Msg kind="info">This site shows devices owned by your account. Farmers add devices in the main app.</Msg>}
      <Loading loading={devs.loading} error={devs.error}>
        {!(devs.data || []).length && <p className="muted">No devices yet. Add one in the main app under Devices.</p>}
        <div className="grid">{(devs.data || []).map((d) => <Card key={d.id} title={d.name || d.uid} right={<Tag v={d.connectivity} />}>
          <p className="muted">{d.uid} · last seen {when(d.last_seen)}{d.battery_pct != null && ` · battery ${d.battery_pct}%`}</p>
          <div className="row">{Object.entries(d.latest).map(([k, v]: any) => <span key={k} className="tag">{k.replace("_", " ")}: {v.value}</span>)}</div>
          <button className="small" onClick={() => setSel(d.id)}>{cur?.id === d.id ? "Selected" : "View"}</button></Card>)}</div>
        {cur && <><h2>{cur.name || cur.uid}</h2><Detail key={cur.id} id={cur.id} /></>}
      </Loading>
    </main></>;
}

createRoot(document.getElementById("root")!).render(<AuthProvider><Monitor /></AuthProvider>);
