import { useState } from "react";
import { api, day, rupees } from "../api";
import { Me } from "../auth";
import { t } from "../i18n";
import { Link, match } from "../router";
import { Card, Field, Loading, Msg, Table, Tag, num, useAction, useLoad, val } from "../ui";

export function Home({ me }: { me: Me }) {
  const d = useLoad(() => api.get("/dashboard"));
  return (
    <Loading loading={d.loading} error={d.error}>{d.data && <>
      <h1>{t("home.welcome")}, {d.data.name}</h1>
      <div className="grid">
        <Card title={t("home.crops")}><div className="stat">{d.data.active_crops}</div><Link to="/crops">{t("nav.crops")}</Link></Card>
        <Card title={t("home.orders")}><div className="stat">{d.data.active_orders}</div><Link to="/orders">{t("nav.orders")}</Link></Card>
        <Card title={t("home.wallet")}><div className="stat">{rupees(d.data.wallet_balance_paise)}</div><Link to="/wallet">{t("nav.wallet")}</Link></Card>
        <Card title={t("home.alerts")}><div className="stat">{d.data.unread_notifications}</div><Link to="/alerts">{t("nav.notifications")}</Link></Card>
      </div>
      {d.data.devices_offline > 0 && <Msg kind="info">{d.data.devices_offline} device(s) are offline. <Link to="/devices">Check devices</Link></Msg>}
      <Card title={t("home.advice")}>
        {d.data.advisories.length ? d.data.advisories.map((a: any) => <p key={a.id}><Tag v={a.severity} /> {a.title}</p>) : <p className="muted">{t("common.none")}</p>}
      </Card>
      <div className="grid">
        <Card title={t("home.harvest")}>{d.data.harvest_soon.length ? d.data.harvest_soon.map((c: any) => <p key={c.id}>{c.name} - {day(c.expected_harvest_date)}</p>) : <p className="muted">{t("common.none")}</p>}</Card>
        <Card title={t("home.appointments")}>{d.data.upcoming_appointments.length ? d.data.upcoming_appointments.map((a: any) => <p key={a.id}>{day(a.at)} - {a.topic}</p>) : <p className="muted">{t("common.none")}</p>}</Card>
      </div>
      <div className="row"><Link className="btn" to="/doctor">{t("nav.doctor")}</Link><Link className="btn alt" to="/assistant">{t("nav.assistant")}</Link><Link className="btn alt" to="/market">{t("nav.market")}</Link></div>
      <p className="muted">{me.full_name}</p>
    </>}</Loading>
  );
}

export function Farms({ path }: { path: string }) {
  const m = match(path, "/farms/:id");
  return m ? <FarmDetail id={m.id} /> : <FarmList />;
}

function FarmList() {
  const farms = useLoad(() => api.get<any[]>("/farm/farms"));
  const [f, setF] = useState<Record<string, string>>({});
  const a = useAction(() => { farms.reload(); setF({}); });
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const here = () => navigator.geolocation?.getCurrentPosition((p) => setF({ ...f, latitude: String(p.coords.latitude.toFixed(5)), longitude: String(p.coords.longitude.toFixed(5)) }));
  return <>
    <h1>{t("nav.farms")}</h1>
    <Loading loading={farms.loading} error={farms.error}>
      <Table rows={farms.data || []} cols={[{ head: t("farm.name"), cell: (r) => <Link to={`/farms/${r.id}`}>{r.name}</Link> }, { head: t("farm.district"), cell: (r) => r.district || "-" }, { head: t("farm.area"), cell: (r) => r.area_acres ?? "-" }]} />
    </Loading>
    <Card title={t("farm.add")}>
      <Field label={t("farm.name")}><input value={f.name || ""} onChange={set("name")} /></Field>
      <Field label={t("farm.village")}><input value={f.village || ""} onChange={set("village")} /></Field>
      <Field label={t("farm.district")}><input value={f.district || ""} onChange={set("district")} /></Field>
      <Field label="State"><input value={f.state || ""} onChange={set("state")} /></Field>
      <Field label={t("farm.area")}><input inputMode="decimal" value={f.area_acres || ""} onChange={set("area_acres")} /></Field>
      <Field label="Soil type"><select value={f.soil_type || ""} onChange={set("soil_type")}><option value="">Not sure</option>{["black", "red", "loam", "sandy loam", "clay", "alluvial"].map((s) => <option key={s}>{s}</option>)}</select></Field>
      <Field label="Water source"><select value={f.irrigation_source || ""} onChange={set("irrigation_source")}><option value="">Choose</option>{["BOREWELL", "CANAL", "RIVER", "DRIP", "RAIN_FED"].map((s) => <option key={s}>{s}</option>)}</select></Field>
      <div className="row"><span className="muted">Location: {f.latitude ? `${f.latitude}, ${f.longitude}` : "not set (needed for weather)"}</span><button className="alt small" onClick={here}>Use my location</button></div>
      {a.box}
      <button disabled={a.busy || !f.name} onClick={() => a.run(() => api.post("/farm/farms", { name: f.name, village: f.village, district: f.district, state: f.state, soil_type: f.soil_type || undefined, irrigation_source: f.irrigation_source || undefined,
        area_acres: num(f.area_acres || ""), latitude: num(f.latitude || ""), longitude: num(f.longitude || "") }))}>{t("common.add")}</button>
    </Card>
  </>;
}

function FarmDetail({ id }: { id: string }) {
  const fields = useLoad(() => api.get<any[]>(`/farm/farms/${id}/fields`), [id]);
  const weather = useLoad(() => api.get(`/farm/farms/${id}/weather`), [id]);
  const adv = useLoad(() => api.get(`/farm/farms/${id}/advisory`), [id]);
  const [nm, setNm] = useState(""); const [ac, setAc] = useState("");
  const a = useAction(() => { fields.reload(); setNm(""); setAc(""); });
  return <>
    <p><Link to="/farms">{t("common.back")}</Link></p><h1>{t("nav.weather")}</h1>
    <Loading loading={weather.loading} error={weather.error}>{weather.data && <Card>
      <div className="stat">{weather.data.current.temp_c}°C <span className="muted">{weather.data.current.summary}</span></div>
      <p className="muted">Humidity {weather.data.current.humidity}% · Wind {weather.data.current.wind_kmh} km/h · Rain now {weather.data.current.rain_mm} mm</p>
      <Table rows={weather.data.daily} cols={[{ head: "Day", cell: (r: any) => day(r.date) }, { head: "Min/Max", cell: (r: any) => `${r.min_c}° / ${r.max_c}°` }, { head: "Rain", cell: (r: any) => `${r.rain_mm} mm` }, { head: "", cell: (r: any) => r.summary }]} />
      {weather.data.alerts.map((x: any, i: number) => <Msg key={i} kind="info">{x.text}</Msg>)}
      <p className="muted">Source: {weather.data.source}</p></Card>}</Loading>
    <h2>{t("home.advice")}</h2>
    <Loading loading={adv.loading} error={adv.error}>{adv.data && <>
      {adv.data.crops.length ? adv.data.crops.map((c: any) => <Card key={c.crop_id} title={`${c.crop}${c.stage ? " - " + c.stage : ""}`}>
        <p><Tag v={c.irrigation.action} /> {c.irrigation.reason}</p>{c.heat_warning && <Msg kind="info">{c.heat_warning}</Msg>}</Card>) : <p className="muted">Add a crop to this farm to see advice.</p>}
      {adv.data.soil?.findings?.map((f: any, i: number) => <p key={i}><Tag v={f.level} /> {f.text}</p>)}
      <p className="muted">{adv.data.disclaimer}</p></>}</Loading>
    <h2>{t("farm.fields")}</h2>
    <Loading loading={fields.loading} error={fields.error}><Table rows={fields.data || []} cols={[{ head: "Name", cell: (r) => r.name }, { head: t("farm.area"), cell: (r) => r.area_acres ?? "-" },
      { head: "", cell: (r) => <button className="small danger" onClick={() => a.run(() => api.del(`/farm/fields/${r.id}`))}>{t("common.delete")}</button> }]} /></Loading>
    <Card><div className="row"><div className="grow"><Field label="Field name"><input value={nm} onChange={(e) => setNm(val(e))} /></Field></div><div className="grow"><Field label={t("farm.area")}><input inputMode="decimal" value={ac} onChange={(e) => setAc(val(e))} /></Field></div></div>
      {a.box}<button disabled={!nm || a.busy} onClick={() => a.run(() => api.post(`/farm/farms/${id}/fields`, { name: nm, area_acres: num(ac) }))}>{t("common.add")}</button></Card>
  </>;
}

export function Crops({ path }: { path: string }) {
  const m = match(path, "/crops/:id");
  return m ? <CropDetail id={m.id} /> : <CropList />;
}

function CropList() {
  const crops = useLoad(() => api.get<any[]>("/farm/crops"));
  const farms = useLoad(() => api.get<any[]>("/farm/farms"));
  const [c, setC] = useState<Record<string, string>>({});
  const a = useAction(() => { crops.reload(); setC({}); });
  const set = (k: string) => (e: { target: { value: string } }) => setC({ ...c, [k]: e.target.value });
  return <>
    <h1>{t("nav.crops")}</h1>
    <Loading loading={crops.loading} error={crops.error}><Table rows={crops.data || []} cols={[{ head: "Crop", cell: (r) => <Link to={`/crops/${r.id}`}>{r.name}</Link> }, { head: "Stage", cell: (r) => r.growth_stage || "-" },
      { head: t("crop.harvest"), cell: (r) => day(r.expected_harvest_date) }, { head: t("common.status"), cell: (r) => <Tag v={r.status} /> }]} /></Loading>
    <Card title={t("crop.add")}>
      <Field label="Farm"><select value={c.farm_id || ""} onChange={set("farm_id")}><option value="">Choose</option>{(farms.data || []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>
      <Field label="Crop"><input value={c.name || ""} onChange={set("name")} placeholder="e.g. Tomato" /></Field>
      <Field label="Season"><select value={c.season || ""} onChange={set("season")}><option value="">Choose</option><option>KHARIF</option><option>RABI</option><option>ZAID</option></select></Field>
      <Field label={t("crop.sowing")}><input type="date" value={c.sowing_date || ""} onChange={set("sowing_date")} /></Field>
      <Field label={t("farm.area")}><input inputMode="decimal" value={c.area_acres || ""} onChange={set("area_acres")} /></Field>
      {a.box}
      <button disabled={a.busy || !c.name || !c.farm_id} onClick={() => a.run(() => api.post("/farm/crops", { farm_id: Number(c.farm_id), name: c.name, season: c.season || undefined, sowing_date: c.sowing_date || undefined, area_acres: num(c.area_acres || "") }))}>{t("common.add")}</button>
    </Card>
  </>;
}

function CropDetail({ id }: { id: string }) {
  const recs = useLoad(() => api.get<any[]>(`/farm/crops/${id}/records`), [id]);
  const sum = useLoad(() => api.get(`/farm/crops/${id}/summary`), [id]);
  const [r, setR] = useState<Record<string, string>>({ kind: "EXPENSE", on_date: new Date().toISOString().slice(0, 10) });
  const a = useAction(() => { recs.reload(); sum.reload(); });
  const set = (k: string) => (e: { target: { value: string } }) => setR({ ...r, [k]: e.target.value });
  return <>
    <p><Link to="/crops">{t("common.back")}</Link></p><h1>{t("crop.records")}</h1>
    {sum.data && <div className="grid"><Card title="Spent"><div className="stat">{rupees(sum.data.cost_paise)}</div></Card><Card title="Sold"><div className="stat">{rupees(sum.data.revenue_paise)}</div></Card>
      <Card title={t("crop.profit")}><div className="stat">{rupees(sum.data.profit_paise)}</div></Card></div>}
    <Loading loading={recs.loading} error={recs.error}><Table rows={recs.data || []} cols={[{ head: "Date", cell: (x) => day(x.on_date) }, { head: "Type", cell: (x) => x.kind }, { head: "Details", cell: (x) => [x.product, x.quantity && `${x.quantity} ${x.unit || ""}`, x.note].filter(Boolean).join(" · ") },
      { head: "Amount", cell: (x) => rupees(x.amount_paise) }, { head: "", cell: (x) => <button className="small danger" onClick={() => a.run(() => api.del(`/farm/records/${x.id}`))}>x</button> }]} /></Loading>
    <Card title={t("common.add")}>
      <Field label="Type"><select value={r.kind} onChange={set("kind")}>{["IRRIGATION", "FERTILIZER", "PESTICIDE", "EXPENSE", "HARVEST", "YIELD", "NOTE"].map((k) => <option key={k}>{k}</option>)}</select></Field>
      <Field label="Date"><input type="date" value={r.on_date} onChange={set("on_date")} /></Field>
      <Field label="Product / item"><input value={r.product || ""} onChange={set("product")} /></Field>
      <div className="row"><div className="grow"><Field label="Quantity"><input inputMode="decimal" value={r.quantity || ""} onChange={set("quantity")} /></Field></div><div className="grow"><Field label="Unit"><input value={r.unit || ""} onChange={set("unit")} placeholder="kg, l, hrs" /></Field></div>
        <div className="grow"><Field label="Amount (Rs)"><input inputMode="decimal" value={r.amount || ""} onChange={set("amount")} /></Field></div></div>
      <Field label="Note"><input value={r.note || ""} onChange={set("note")} /></Field>{a.box}
      <button disabled={a.busy} onClick={() => a.run(() => api.post(`/farm/crops/${id}/records`, { kind: r.kind, on_date: r.on_date, product: r.product || undefined, quantity: num(r.quantity || ""), unit: r.unit || undefined, amount_rupees: num(r.amount || ""), note: r.note || undefined }))}>{t("common.add")}</button>
    </Card>
  </>;
}

export function Soil() {
  const read = useLoad(() => api.get<any[]>("/farm/soil"));
  const tests = useLoad(() => api.get<any[]>("/farm/soil-tests"));
  const farms = useLoad(() => api.get<any[]>("/farm/farms"));
  const centers = useLoad(() => api.get<any[]>("/farm/soil-centers"));
  const [s, setS] = useState<Record<string, string>>({ on_date: new Date().toISOString().slice(0, 10) });
  const [b, setB] = useState<Record<string, string>>({ collection: "DROP_OFF" });
  const a = useAction(() => { read.reload(); tests.reload(); });
  const ss = (k: string) => (e: { target: { value: string } }) => setS({ ...s, [k]: e.target.value });
  const bb = (k: string) => (e: { target: { value: string } }) => setB({ ...b, [k]: e.target.value });
  const farmSel = (get: Record<string, string>, set: (k: string) => (e: { target: { value: string } }) => void) =>
    <Field label="Farm"><select value={get.farm_id || ""} onChange={set("farm_id")}><option value="">Choose</option>{(farms.data || []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>;
  return <>
    <h1>{t("nav.soil")}</h1>
    <Loading loading={read.loading} error={read.error}>{(read.data || []).slice(0, 5).map((x) => <Card key={x.id} title={`${day(x.on_date)} (${x.source.toLowerCase()})`}>
      <p className="muted">pH {x.ph ?? "-"} · N {x.nitrogen ?? "-"} · P {x.phosphorus ?? "-"} · K {x.potassium ?? "-"} · moisture {x.moisture ?? "-"}%</p>
      {x.findings.map((f: any, i: number) => <p key={i}><Tag v={f.level} /> {f.item}: {f.text}</p>)}</Card>)}{!(read.data || []).length && <p className="muted">{t("common.none")}</p>}</Loading>
    <Card title="Enter soil values">
      {farmSel(s, ss)}<Field label="Date"><input type="date" value={s.on_date} onChange={ss("on_date")} /></Field>
      <div className="row">{[["ph", "pH"], ["nitrogen", "Nitrogen"], ["phosphorus", "Phosphorus"], ["potassium", "Potassium"], ["organic_carbon", "Organic carbon %"], ["moisture", "Moisture %"]].map(([k, l]) =>
        <div className="grow" key={k}><Field label={l}><input inputMode="decimal" value={s[k] || ""} onChange={ss(k)} /></Field></div>)}</div>{a.box}
      <button disabled={a.busy || !s.farm_id} onClick={() => a.run(() => api.post("/farm/soil", { farm_id: Number(s.farm_id), on_date: s.on_date, ph: num(s.ph || ""), nitrogen: num(s.nitrogen || ""), phosphorus: num(s.phosphorus || ""), potassium: num(s.potassium || ""), organic_carbon: num(s.organic_carbon || ""), moisture: num(s.moisture || "") }))}>{t("common.save")}</button>
    </Card>
    <h2>Soil testing</h2>
    <Loading loading={tests.loading} error={tests.error}><Table rows={tests.data || []} cols={[{ head: "Code", cell: (x) => x.tracking_code }, { head: "Centre", cell: (x) => x.center_name }, { head: "Date", cell: (x) => day(x.preferred_date) }, { head: t("common.status"), cell: (x) => <Tag v={x.status} /> },
      { head: "", cell: (x) => ["REQUESTED", "CONFIRMED"].includes(x.status) ? <button className="small alt" onClick={() => a.run(() => api.post(`/farm/soil-tests/${x.id}/cancel`))}>{t("common.cancel")}</button> : x.interpretation }]} /></Loading>
    <Card title="Book a soil test">
      <Field label="Centre"><select value={b.center_id || ""} onChange={bb("center_id")}><option value="">Choose</option>{(centers.data || []).map((c) => <option key={c.id} value={c.id}>{c.name} - {c.district} ({rupees(c.fee_paise)})</option>)}</select></Field>
      {farmSel(b, bb)}<Field label="Preferred date"><input type="date" value={b.preferred_date || ""} onChange={bb("preferred_date")} /></Field>
      <Field label="Sample"><select value={b.collection} onChange={bb("collection")}><option value="DROP_OFF">I will drop it at the centre</option><option value="PICKUP">Please collect from my farm</option></select></Field>
      <button disabled={a.busy || !b.center_id || !b.farm_id || !b.preferred_date} onClick={() => a.run(() => api.post("/farm/soil-tests", { center_id: Number(b.center_id), farm_id: Number(b.farm_id), preferred_date: b.preferred_date, collection: b.collection }), "Booked")}>{t("common.submit")}</button>
    </Card>
  </>;
}
