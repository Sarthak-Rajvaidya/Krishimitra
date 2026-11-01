import { useState } from "react";
import { api, errText, rupees, when } from "../api";
import { Me } from "../auth";
import { getLang, LANGS, setLang, t } from "../i18n";
import { Link, match } from "../router";
import { Card, Field, Loading, Msg, Table, Tag, num, useAction, useLoad, val } from "../ui";

export function Machines() {
  const [cat, setCat] = useState(""); const [dist, setDist] = useState("");
  const list = useLoad(() => api.get<any[]>(`/machines?category=${cat}&district=${encodeURIComponent(dist)}`), [cat, dist]);
  const mine = useLoad(() => api.get<any>("/machines/bookings"));
  const [b, setB] = useState<Record<string, string>>({ rate_type: "DAILY", units: "1" });
  const [pick, setPick] = useState<any>(null);
  const a = useAction(() => mine.reload());
  return <><h1>{t("nav.machines")}</h1>
    <div className="row"><select value={cat} onChange={(e) => setCat(val(e))} aria-label="Type"><option value="">All types</option>{["TRACTOR", "HARVESTER", "ROTAVATOR", "CULTIVATOR", "SEED_DRILL", "SPRAYER", "THRESHER", "JCB", "PUMP"].map((c) => <option key={c}>{c}</option>)}</select>
      <input style={{ maxWidth: 220 }} placeholder={t("farm.district")} value={dist} onChange={(e) => setDist(val(e))} /><Link className="btn alt" to="/machines/mine">List my machine</Link></div>
    <Loading loading={list.loading} error={list.error}><div className="grid">{(list.data || []).map((m) => <Card key={m.id} title={m.name}>
      <p className="muted">{m.category} · {m.district}</p><p>{m.hourly_paise ? rupees(m.hourly_paise) + "/hr  " : ""}{m.daily_paise ? rupees(m.daily_paise) + "/day" : ""}</p>
      {m.rating_count ? <p>★ {m.rating_avg} ({m.rating_count})</p> : null}<button className="small" onClick={() => setPick(m)}>Book</button></Card>)}</div>
      {!(list.data || []).length && <p className="muted">{t("common.none")}</p>}</Loading>
    {pick && <Card title={`Book ${pick.name}`}>
      <Field label="Start"><input type="datetime-local" value={b.start_at || ""} onChange={(e) => setB({ ...b, start_at: val(e) })} /></Field>
      <div className="row"><select value={b.rate_type} onChange={(e) => setB({ ...b, rate_type: val(e) })}><option value="DAILY">Days</option><option value="HOURLY">Hours</option></select><input style={{ width: 90 }} inputMode="numeric" value={b.units} onChange={(e) => setB({ ...b, units: val(e) })} aria-label="Count" /></div>
      {a.box}<button disabled={!b.start_at || a.busy} onClick={() => a.run(() => api.post("/machines/book", { machine_id: pick.id, start_at: new Date(b.start_at).toISOString(), units: Number(b.units), rate_type: b.rate_type }), "Request sent to the owner")}>{t("common.submit")}</button></Card>}
    <h2>My rentals</h2><Loading loading={mine.loading} error={mine.error}>{mine.data && <Table rows={mine.data.rentals} cols={[{ head: "Machine", cell: (r: any) => r.machine }, { head: "When", cell: (r: any) => when(r.start_at) }, { head: "Amount", cell: (r: any) => rupees(r.amount_paise) }, { head: t("common.status"), cell: (r: any) => <Tag v={r.status} /> },
      { head: "", cell: (r: any) => <div className="row">{r.status === "ACCEPTED" && r.payment_status === "UNPAID" && <button className="small" onClick={() => a.run(() => api.post(`/machines/bookings/${r.id}/pay`), "Paid from wallet")}>Pay</button>}
        {["REQUESTED", "ACCEPTED"].includes(r.status) && <button className="small alt" onClick={() => a.run(() => api.post(`/machines/bookings/${r.id}/cancel`))}>{t("common.cancel")}</button>}</div> }]} />}</Loading></>;
}

export function MyMachines() {
  const m = useLoad(() => api.get<any>("/machines/bookings"));
  const mine = useLoad(() => api.get<any[]>("/machines/mine"));
  const [f, setF] = useState<Record<string, string>>({ category: "TRACTOR" });
  const a = useAction(() => { m.reload(); mine.reload(); });
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return <><p><Link to="/machines">{t("common.back")}</Link></p><h1>My machines</h1>
    <Loading loading={mine.loading} error={mine.error}><Table rows={mine.data || []} cols={[{ head: "Name", cell: (x) => x.name }, { head: "Approval", cell: (x) => <Tag v={x.approval_status} /> }, { head: "Available", cell: (x) => <button className="small alt" onClick={() => a.run(() => api.post(`/machines/${x.id}/availability?available=${!x.is_available}`))}>{x.is_available ? "Yes - pause" : "No - resume"}</button> }]} /></Loading>
    <h2>Requests</h2>{m.data && <Table rows={m.data.requests} cols={[{ head: "Machine", cell: (r: any) => r.machine }, { head: "When", cell: (r: any) => when(r.start_at) }, { head: "Amount", cell: (r: any) => rupees(r.amount_paise) }, { head: t("common.status"), cell: (r: any) => <Tag v={r.status} /> },
      { head: "", cell: (r: any) => <div className="row">{r.status === "REQUESTED" && <><button className="small" onClick={() => a.run(() => api.post(`/machines/bookings/${r.id}/decide`, { action: "ACCEPT" }))}>Accept</button><button className="small alt" onClick={() => a.run(() => api.post(`/machines/bookings/${r.id}/decide`, { action: "REJECT" }))}>Decline</button></>}
        {r.status === "ACCEPTED" && r.payment_status === "PAID" && <button className="small" onClick={() => a.run(() => api.post(`/machines/bookings/${r.id}/decide`, { action: "COMPLETE" }))}>Mark complete</button>}</div> }]} />}
    <Card title="List a machine"><Field label="Type"><select value={f.category} onChange={set("category")}>{["TRACTOR", "HARVESTER", "ROTAVATOR", "CULTIVATOR", "SEED_DRILL", "SPRAYER", "THRESHER", "JCB", "PUMP", "OTHER"].map((c) => <option key={c}>{c}</option>)}</select></Field>
      <Field label="Name / model"><input value={f.name || ""} onChange={set("name")} /></Field><Field label={t("farm.district")}><input value={f.district || ""} onChange={set("district")} /></Field>
      <div className="row"><div className="grow"><Field label="Rate per hour (Rs)"><input inputMode="decimal" value={f.hourly || ""} onChange={set("hourly")} /></Field></div><div className="grow"><Field label="Rate per day (Rs)"><input inputMode="decimal" value={f.daily || ""} onChange={set("daily")} /></Field></div></div>
      {a.box}<button disabled={!f.name || a.busy} onClick={() => a.run(() => api.post("/machines", { category: f.category, name: f.name, district: f.district, hourly_rupees: num(f.hourly || ""), daily_rupees: num(f.daily || "") }), "Submitted. It appears after admin approval.")}>{t("common.submit")}</button></Card></>;
}

export function Devices({ path }: { path: string }) {
  const m = match(path, "/devices/:id");
  return m ? <DeviceDetail id={m.id} /> : <DeviceList />;
}

function DeviceList() {
  const d = useLoad(() => api.get<any[]>("/iot/devices"));
  const farms = useLoad(() => api.get<any[]>("/farm/farms"));
  const [f, setF] = useState<Record<string, string>>({ kind: "NODE" });
  const [token, setToken] = useState<any>(null);
  const a = useAction(() => d.reload());
  return <><h1>{t("nav.devices")}</h1><p><a href="/iot.html" target="_blank" rel="noreferrer">{t("iot.open")}</a></p>
    <Loading loading={d.loading} error={d.error}><div className="grid">{(d.data || []).map((x) => <Card key={x.id} title={x.name || x.uid} right={<Tag v={x.connectivity} />}>
      <p className="muted">{x.uid} · {x.kind}</p>{x.latest.soil_moisture && <p>{t("iot.moisture")}: <b>{x.latest.soil_moisture.value}%</b></p>}{x.latest.temperature && <p>Temperature: {x.latest.temperature.value}°C</p>}
      <Link to={`/devices/${x.id}`}>Open</Link></Card>)}</div>{!(d.data || []).length && <p className="muted">{t("common.none")}</p>}</Loading>
    <Card title="Add a device"><Field label="Name"><input value={f.name || ""} onChange={(e) => setF({ ...f, name: val(e) })} /></Field>
      <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: val(e) })}><option value="NODE">Sensor node</option><option value="PUMP_CONTROLLER">Pump controller</option><option value="COMBO">Sensors + pump</option></select></Field>
      <Field label="Farm"><select value={f.farm_id || ""} onChange={(e) => setF({ ...f, farm_id: val(e) })}><option value="">Choose</option>{(farms.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
      {a.box}<button disabled={!f.name || !f.farm_id || a.busy} onClick={() => a.run(async () => setToken(await api.post("/iot/devices", { name: f.name, kind: f.kind, farm_id: Number(f.farm_id) })))}>{t("common.add")}</button></Card>
    {token && <Msg kind="info">Device id <b>{token.uid}</b> · token <b>{token.device_token}</b><br />{token.note}</Msg>}</>;
}

function DeviceDetail({ id }: { id: string }) {
  const d = useLoad(() => api.get<any[]>("/iot/devices").then((l) => l.find((x) => String(x.id) === id)), [id]);
  const hist = useLoad(() => api.get(`/iot/devices/${id}/history?metric=soil_moisture&hours=24`), [id]);
  const irr = useLoad(() => api.get(`/iot/devices/${id}/irrigation`).catch(() => null), [id]);
  const [c, setC] = useState<any>(null);
  const a = useAction(() => { d.reload(); irr.reload(); });
  const cfg = c || irr.data?.config;
  return <><p><Link to="/devices">{t("common.back")}</Link></p>
    <Loading loading={d.loading} error={d.error}>{d.data && <><h1>{d.data.name || d.data.uid}</h1>
      <Card><p>Status: <Tag v={d.data.connectivity} /> · last seen {when(d.data.last_seen)} {d.data.battery_pct != null && `· battery ${d.data.battery_pct}%`}</p>
        <div className="row">{Object.entries(d.data.latest).map(([k, v]: any) => <span key={k} className="tag">{k.replace("_", " ")}: {v.value}</span>)}</div></Card>
      {hist.data && <Card title="Soil moisture, last 24 hours"><Chart points={hist.data.points.map((p: any) => p.v)} /></Card>}
      {irr.data?.config && <Card title={t("iot.pump")} right={<Tag v={irr.data.pump_running ? "ON" : "OFF"} />}>
        <div className="row"><button onClick={() => a.run(() => api.post(`/iot/devices/${id}/pump`, { action: "ON", minutes: 15 }), "Command sent. The pump starts when the device checks in.")} disabled={a.busy}>{t("iot.on")} (15 min)</button>
          <button className="alt" onClick={() => a.run(() => api.post(`/iot/devices/${id}/pump`, { action: "OFF" }), "Stop command sent")}>{t("iot.off")}</button></div>
        <p className="muted">Using the buttons pauses automatic irrigation for 1 hour. The pump never runs longer than your limit, when the tank is low, or (if enabled) when it is raining.</p>
        <Field label="Mode"><select value={cfg.mode} onChange={(e) => setC({ ...cfg, mode: val(e) })}><option value="MANUAL">{t("iot.manual")}</option><option value="AUTO">{t("iot.auto")} (by soil moisture)</option><option value="SCHEDULE">Schedule</option></select></Field>
        <div className="row"><div className="grow"><Field label="Start below %"><input inputMode="numeric" value={cfg.moisture_low} onChange={(e) => setC({ ...cfg, moisture_low: Number(val(e)) })} /></Field></div>
          <div className="grow"><Field label="Stop above %"><input inputMode="numeric" value={cfg.moisture_high} onChange={(e) => setC({ ...cfg, moisture_high: Number(val(e)) })} /></Field></div>
          <div className="grow"><Field label="Max minutes per run"><input inputMode="numeric" value={cfg.max_minutes} onChange={(e) => setC({ ...cfg, max_minutes: Number(val(e)) })} /></Field></div></div>
        <label><input type="checkbox" checked={cfg.rain_lock} onChange={() => setC({ ...cfg, rain_lock: !cfg.rain_lock })} /> Do not irrigate when it is raining</label>
        <label><input type="checkbox" checked={cfg.low_water_lock} onChange={() => setC({ ...cfg, low_water_lock: !cfg.low_water_lock })} /> Do not run when the water tank is low</label>
        {a.box}<button onClick={() => a.run(() => api.put(`/iot/devices/${id}/irrigation`, cfg), "Saved")}>{t("common.save")}</button>
        <h3>Recent runs</h3><Table rows={irr.data.history} cols={[{ head: "Started", cell: (r: any) => when(r.started_at) }, { head: "Minutes", cell: (r: any) => r.minutes ?? "running" }, { head: "By", cell: (r: any) => r.source }]} /></Card>}</>}</Loading></>;
}

export function Chart({ points }: { points: number[] }) {
  if (points.length < 2) return <p className="muted">No readings yet.</p>;
  const w = 600, h = 140, lo = Math.min(...points), hi = Math.max(...points), sp = hi - lo || 1;
  const d = points.map((v, i) => `${i ? "L" : "M"}${(i / (points.length - 1)) * w},${h - ((v - lo) / sp) * (h - 20) - 10}`).join(" ");
  return <div className="scroll"><svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="chart"><path d={d} fill="none" stroke="#2f6b3a" strokeWidth="2" /></svg><div className="muted">Low {lo} · High {hi}</div></div>;
}

export function Experts() {
  const [q, setQ] = useState("");
  const list = useLoad(() => api.get<any[]>(`/experts?q=${encodeURIComponent(q)}`), [q]);
  const appts = useLoad(() => api.get<any[]>("/appointments"));
  const [pick, setPick] = useState<any>(null); const [b, setB] = useState<Record<string, string>>({ mode: "CHAT" });
  const [chat, setChat] = useState<any>(null);
  const a = useAction(() => appts.reload());
  const diag = Number((location.hash.split("diagnosis=")[1] || "").split("&")[0]) || undefined;
  return <><h1>{t("nav.experts")}</h1><input value={q} onChange={(e) => setQ(val(e))} placeholder={t("common.search")} aria-label={t("common.search")} />
    <Loading loading={list.loading} error={list.error}><div className="grid">{(list.data || []).map((x) => <Card key={x.id} title={x.name}>
      <p className="muted">{x.qualification} · {x.experience_years} yrs · {x.district}</p><p>{x.specialization.join(", ")}</p><p>{rupees(x.fee_paise)} per consultation {x.rating_count ? `· ★ ${x.rating_avg}` : ""}</p><button className="small" onClick={() => setPick(x)}>Book</button></Card>)}</div></Loading>
    {pick && <Card title={`Book ${pick.name}`}><Field label="How"><select value={b.mode} onChange={(e) => setB({ ...b, mode: val(e) })}>{pick.modes.map((m: string) => <option key={m}>{m}</option>)}</select></Field>
      <Field label="When"><input type="datetime-local" value={b.when || ""} onChange={(e) => setB({ ...b, when: val(e) })} /></Field><Field label="What is the problem?"><textarea value={b.topic || ""} onChange={(e) => setB({ ...b, topic: val(e) })} /></Field>
      <label><input type="checkbox" checked={b.pay === "1"} onChange={() => setB({ ...b, pay: b.pay === "1" ? "0" : "1" })} /> Pay {rupees(pick.fee_paise)} from wallet now</label>{a.box}
      <button disabled={!b.when || !b.topic || a.busy} onClick={() => a.run(() => api.post("/appointments", { expert_id: pick.id, mode: b.mode, scheduled_at: new Date(b.when).toISOString(), topic: b.topic, diagnosis_id: diag, pay_from_wallet: b.pay === "1" }), "Requested")}>{t("common.submit")}</button></Card>}
    <h2>My consultations</h2><Loading loading={appts.loading} error={appts.error}><Table rows={appts.data || []} cols={[{ head: "With", cell: (x) => x.other }, { head: "When", cell: (x) => when(x.scheduled_at) }, { head: "Topic", cell: (x) => x.topic }, { head: t("common.status"), cell: (x) => <Tag v={x.status} /> },
      { head: "", cell: (x) => <div className="row"><button className="small alt" onClick={() => setChat(x)}>Chat</button>{x.meeting_url && <a href={x.meeting_url} target="_blank" rel="noreferrer">Join</a>}
        {!x.paid && x.fee_paise > 0 && ["REQUESTED", "CONFIRMED"].includes(x.status) && <button className="small" onClick={() => a.run(() => api.post(`/appointments/${x.id}/pay`))}>Pay</button>}</div> }]} /></Loading>
    {chat && <Chat appt={chat} />}</>;
}

function Chat({ appt }: { appt: any }) {
  const m = useLoad(() => api.get<any[]>(`/appointments/${appt.id}/messages`), [appt.id]);
  const [x, setX] = useState(""); const a = useAction(() => { m.reload(); setX(""); });
  return <Card title={`Chat with ${appt.other}`} right={<button className="small alt" onClick={() => m.reload()}>Refresh</button>}>
    {appt.expert_notes && <Msg kind="info">Expert's advice: {appt.expert_notes}</Msg>}
    <div className="chat">{(m.data || []).map((x) => <div key={x.id} className={"bubble " + (x.mine ? "me" : "bot")}>{x.body}</div>)}</div>{a.box}
    <div className="row"><div className="grow"><input value={x} onChange={(e) => setX(val(e))} aria-label="Message" /></div><button disabled={!x} onClick={() => a.run(() => api.post(`/appointments/${appt.id}/messages`, { body: x }))}>{t("assistant.send")}</button></div></Card>;
}

export function Community() {
  const [kind, setKind] = useState("");
  const feed = useLoad(() => api.get<any[]>(`/community/posts?kind=${kind}`), [kind]);
  const [p, setP] = useState<Record<string, string>>({ kind: "QUESTION" });
  const [open, setOpen] = useState<number | null>(null);
  const a = useAction(() => { feed.reload(); setP({ kind: "QUESTION" }); });
  return <><h1>{t("nav.community")}</h1>
    <div className="tabs">{[["", "All"], ["QUESTION", "Questions"], ["EXPERIENCE", "Experiences"], ["SUCCESS_STORY", "Success stories"]].map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>)}</div>
    <Card title="Share or ask"><select value={p.kind} onChange={(e) => setP({ ...p, kind: val(e) })}><option value="QUESTION">Question</option><option value="EXPERIENCE">Experience</option><option value="SUCCESS_STORY">Success story</option><option value="POST">General</option></select>
      <textarea value={p.body || ""} onChange={(e) => setP({ ...p, body: val(e) })} placeholder="Write here" />{a.box}<button disabled={(p.body || "").length < 3 || a.busy} onClick={() => a.run(() => api.post("/community/posts", { kind: p.kind, body: p.body }))}>Post</button></Card>
    <Loading loading={feed.loading} error={feed.error}>{(feed.data || []).map((x) => <Card key={x.id}><p className="muted">{x.author.name} · {x.kind.toLowerCase().replace("_", " ")} · {when(x.at)}</p><p>{x.body}</p>
      <div className="row"><button className="small alt" onClick={() => api.post(`/community/posts/${x.id}/like`).then(() => feed.reload())}>👍 {x.likes}</button><button className="small alt" onClick={() => setOpen(open === x.id ? null : x.id)}>Replies ({x.comments})</button>
        <button className="small alt" onClick={() => { const r = prompt("Why are you reporting this?"); if (r) api.post("/community/reports", { target_type: "POST", target_id: x.id, reason: r }).catch((e) => alert(errText(e))); }}>Report</button></div>
      {open === x.id && <Thread id={x.id} />}</Card>)}</Loading></>;
}

function Thread({ id }: { id: number }) {
  const th = useLoad(() => api.get(`/community/posts/${id}`), [id]); const [x, setX] = useState(""); const a = useAction(() => { th.reload(); setX(""); });
  return <div style={{ marginTop: 8 }}>{th.data?.thread.map((c: any) => <p key={c.id}><b>{c.author.name}</b> {c.is_answer && <Tag v="APPROVED" />}: {c.body}</p>)}{a.box}
    <div className="row"><div className="grow"><input value={x} onChange={(e) => setX(val(e))} aria-label="Reply" /></div><button className="small" disabled={!x} onClick={() => a.run(() => api.post(`/community/posts/${id}/comments`, { body: x }))}>Reply</button></div></div>;
}

export function Learn({ schemes }: { schemes?: boolean }) {
  const [kind, setKind] = useState(schemes ? "SCHEME" : ""); const [q, setQ] = useState("");
  const list = useLoad(() => api.get<any[]>(`/content?kind=${kind}&q=${encodeURIComponent(q)}&language=${getLang()}`), [kind, q]);
  const [open, setOpen] = useState<any>(null);
  const kinds = schemes ? [["SCHEME", "Schemes"], ["LOAN", "Loans"], ["INSURANCE", "Insurance"]] : [["", "All"], ["ARTICLE", "Articles"], ["GUIDE", "Guides"], ["VIDEO", "Videos"], ["TRAINING", "Training"], ["FAQ", "FAQ"], ["DISEASE", "Diseases"], ["PEST", "Pests"]];
  const a = useAction();
  return <><h1>{schemes ? t("nav.schemes") : t("nav.learn")}</h1>
    <div className="tabs">{kinds.map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>)}</div>
    <input value={q} onChange={(e) => setQ(val(e))} placeholder={t("common.search")} aria-label={t("common.search")} />{a.box}
    <Loading loading={list.loading} error={list.error}>{(list.data || []).map((c) => <Card key={c.id} title={c.title} right={c.needs_verification && ["SCHEME", "LOAN", "INSURANCE"].includes(c.kind) ? <span className="tag warn">check official source</span> : undefined}>
      <p>{c.summary}</p>{c.disclaimer && <p className="muted">{c.disclaimer}</p>}
      <div className="row"><button className="small alt" onClick={() => api.get(`/content/${c.id}`).then(setOpen)}>Read</button>{c.url && <a href={c.url} target="_blank" rel="noreferrer">Official link</a>}
        <button className="small alt" onClick={() => a.run(() => api.post(`/content/${c.id}/save`), "Saved")}>Save</button>
        {c.kind === "SCHEME" && <button className="small alt" onClick={() => a.run(() => api.put("/scheme-applications", { content_id: c.id, status: "PLANNED" }), "Added to your tracker")}>Track</button>}</div></Card>)}</Loading>
    {open && <Card title={open.title} right={<button className="small alt" onClick={() => setOpen(null)}>x</button>}>
      {["body", "eligibility", "documents_required", "procedure", "benefits"].map((k) => open[k] && <div key={k}><h3>{k.replace("_", " ")}</h3><p style={{ whiteSpace: "pre-wrap" }}>{open[k]}</p></div>)}</Card>}</>;
}

export function Wallet() {
  const w = useLoad(() => api.get("/wallet"));
  const [amt, setAmt] = useState("500"); const [g, setG] = useState<any>(null);
  const a = useAction(() => { w.reload(); setG(null); });
  return <><h1>{t("nav.wallet")}</h1>
    <Loading loading={w.loading} error={w.error}>{w.data && <><Card title={t("wallet.balance")}><div className="stat">{rupees(w.data.balance_paise)}</div></Card>
      <Card title={t("wallet.add")}><div className="row"><input style={{ maxWidth: 140 }} inputMode="numeric" value={amt} onChange={(e) => setAmt(val(e))} aria-label="Amount in rupees" /><button disabled={a.busy} onClick={() => a.run(async () => setG(await api.post("/wallet/topup", { amount_rupees: Number(amt) })))}>Continue</button></div>
        {g?.simulated && <><Msg kind="info">Test mode: no real money moves.</Msg><button onClick={() => a.run(() => api.post("/wallet/confirm", { gateway_order_id: g.gateway_order_id, payment_id: "sim" }), "Added")}>Confirm test payment</button></>}
        {g && !g.simulated && <Msg kind="info">Online payments need the payment window from your provider. Contact support if it does not open.</Msg>}{a.box}</Card>
      <h2>History</h2><Table rows={w.data.history} cols={[{ head: "When", cell: (x: any) => when(x.at) }, { head: "Type", cell: (x: any) => x.kind.replace(/_/g, " ").toLowerCase() }, { head: "Amount", cell: (x: any) => rupees(x.amount_paise) }, { head: "Balance", cell: (x: any) => rupees(x.balance_after_paise) }]} /></>}</Loading></>;
}

export function Alerts() {
  const n = useLoad(() => api.get("/notifications")); const a = useAction(() => n.reload());
  return <><h1>{t("nav.notifications")}</h1><button className="alt" onClick={() => a.run(() => api.post("/notifications/read", {}))}>Mark all as read</button>
    <Loading loading={n.loading} error={n.error}>{n.data?.items.map((x: any) => <Card key={x.id}><b>{x.title}</b> {!x.read && <span className="tag warn">new</span>}<p>{x.body}</p><span className="muted">{when(x.at)}</span></Card>)}{!n.data?.items.length && <p className="muted">{t("common.none")}</p>}</Loading></>;
}

export function Support() {
  const tk = useLoad(() => api.get<any[]>("/tickets")); const [f, setF] = useState<Record<string, string>>({ category: "ORDER", kind: "TICKET" }); const [open, setOpen] = useState<number | null>(null);
  const a = useAction(() => { tk.reload(); setF({ category: "ORDER", kind: "TICKET" }); });
  return <><h1>{t("nav.support")}</h1>
    <Card title={t("support.new")}><div className="row"><select value={f.kind} onChange={(e) => setF({ ...f, kind: val(e) })}><option value="TICKET">Help request</option><option value="COMPLAINT">Complaint</option><option value="FEEDBACK">Feedback</option></select>
      <select value={f.category} onChange={(e) => setF({ ...f, category: val(e) })}>{["ORDER", "DELIVERY", "PAYMENT", "SUPPLIER", "EXPERT", "MACHINE", "APP", "IOT", "OTHER"].map((c) => <option key={c}>{c}</option>)}</select></div>
      <Field label="Subject"><input value={f.subject || ""} onChange={(e) => setF({ ...f, subject: val(e) })} /></Field><Field label="Details"><textarea value={f.message || ""} onChange={(e) => setF({ ...f, message: val(e) })} /></Field>{a.box}
      <button disabled={(f.subject || "").length < 3 || (f.message || "").length < 3 || a.busy} onClick={() => a.run(() => api.post("/tickets", f), "Submitted")}>{t("common.submit")}</button></Card>
    <Loading loading={tk.loading} error={tk.error}><Table rows={tk.data || []} cols={[{ head: "Subject", cell: (x) => <a href="#/support" onClick={(e) => { e.preventDefault(); setOpen(open === x.id ? null : x.id); }}>{x.subject}</a> }, { head: t("common.status"), cell: (x) => <Tag v={x.status} /> }, { head: "Resolution", cell: (x) => x.resolution || "-" }]} /></Loading>
    {open && <TicketThread id={open} />}</>;
}

function TicketThread({ id }: { id: number }) {
  const t2 = useLoad(() => api.get(`/tickets/${id}`), [id]); const [x, setX] = useState(""); const a = useAction(() => { t2.reload(); setX(""); });
  return <Card title={t2.data?.subject}>{t2.data?.messages.map((m: any, i: number) => <div key={i} className={"bubble " + (m.mine ? "me" : "bot")}><b>{m.from}</b><br />{m.body}</div>)}{a.box}
    <div className="row"><div className="grow"><input value={x} onChange={(e) => setX(val(e))} aria-label="Reply" /></div><button disabled={!x} onClick={() => a.run(() => api.post(`/tickets/${id}/reply`, { body: x }))}>Reply</button></div></Card>;
}

export function Settings({ me }: { me: Me }) {
  const prof = useLoad(() => api.get("/account/profile")); const sess = useLoad(() => api.get<any[]>("/auth/sessions")); const docs = useLoad(() => api.get<any[]>("/account/documents"));
  const [pw, setPw] = useState({ old_password: "", new_password: "" }); const [dt, setDt] = useState("AADHAAR"); const [file, setFile] = useState<File | null>(null);
  const a = useAction(() => { prof.reload(); sess.reload(); docs.reload(); });
  const prefs = prof.data?.notif_prefs || {}; const priv = prof.data?.privacy || {};
  return <><h1>{t("nav.settings")}</h1>
    <Card title={t("common.language")}><select value={getLang()} onChange={(e) => { setLang(val(e) as any); a.run(() => api.patch("/account/profile", { language: val(e) })); }} aria-label={t("common.language")}>{LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}</select>
      <label><input type="checkbox" defaultChecked={localStorage.getItem("km_autoread") === "1"} onChange={(e) => localStorage.setItem("km_autoread", e.target.checked ? "1" : "0")} /> Read assistant answers aloud automatically</label></Card>
    <Card title="Alerts"><div className="row">{["in_app", "sms", "email"].map((k) => <label key={k}><input type="checkbox" checked={!!prefs[k]} onChange={() => a.run(() => api.put("/account/notification-prefs", { [k]: !prefs[k] }))} /> {k.replace("_", "-")}</label>)}</div></Card>
    <Card title={t("settings.privacy")}><label><input type="checkbox" checked={priv.community_profile_public !== false} onChange={() => a.run(() => api.put("/account/privacy", { community_profile_public: priv.community_profile_public === false }))} /> Show my full name in the community</label>
      <label><input type="checkbox" checked={priv.share_with_experts !== false} onChange={() => a.run(() => api.put("/account/privacy", { share_with_experts: priv.share_with_experts === false }))} /> Let experts see my crop data when I book them</label></Card>
    {me.role !== "FARMER" && !["FINANCE", "DEVELOPER", "FOUNDER", "ADMIN", "SUPER_ADMIN", "DISTRICT_MANAGER"].includes(me.role) && <Card title="Verification documents"><Table rows={docs.data || []} cols={[{ head: "Type", cell: (d) => d.doc_type }, { head: "File", cell: (d) => d.name }, { head: t("common.status"), cell: (d) => <Tag v={d.status} /> }, { head: "Note", cell: (d) => d.note || "" }]} />
      <div className="row"><select value={dt} onChange={(e) => setDt(val(e))}>{["AADHAAR", "PAN", "GST", "SHOP_LICENCE", "DRIVING_LICENCE", "VEHICLE_RC", "CERTIFICATE", "LAB_ACCREDITATION", "OTHER"].map((x) => <option key={x}>{x}</option>)}</select><input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <button disabled={!file} onClick={() => a.run(() => { const fd = new FormData(); fd.append("doc_type", dt); fd.append("file", file!); return api.upload("/account/documents", fd); }, "Uploaded")}>Upload</button></div><p className="muted">Documents are stored encrypted and only seen by reviewing staff.</p></Card>}
    <Card title="Change password"><Field label="Current password"><input type="password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: val(e) })} /></Field><Field label="New password"><input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: val(e) })} /></Field>
      <button onClick={() => a.run(() => api.post("/auth/password/change", pw), "Password changed")}>{t("common.save")}</button></Card>
    <Card title="Signed-in devices"><Table rows={sess.data || []} cols={[{ head: "Device", cell: (s) => (s.device || "").slice(0, 60) }, { head: "Since", cell: (s) => when(s.created_at) }, { head: "", cell: (s) => s.current ? <Tag v="ACTIVE" /> : <button className="small alt" onClick={() => a.run(() => api.del(`/auth/sessions/${s.id}`))}>Sign out</button> }]} /></Card>
    <Card title={t("settings.delete")}><p className="muted">Your personal details are removed after review. Order and payment records are kept as the law requires.</p><button className="danger" onClick={() => confirm("Request deletion of your account?") && a.run(() => api.post("/account/deletion-request", {}), "Request sent")}>{t("settings.delete")}</button></Card>
    {a.box}</>;
}
