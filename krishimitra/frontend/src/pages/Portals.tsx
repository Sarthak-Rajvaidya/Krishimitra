import { useState } from "react";
import { api, rupees, when } from "../api";
import { Me } from "../auth";
import { Card, Field, Loading, Msg, Table, Tag, num, useAction, useLoad, val } from "../ui";

const ORDER_NEXT: Record<string, string> = { PLACED: "CONFIRMED", CONFIRMED: "PACKED", PACKED: "READY_FOR_DISPATCH" };

export function Supplier() {
  const [tab, setTab] = useState("orders");
  const orders = useLoad(() => api.get<any[]>("/supplier/orders"));
  const prods = useLoad(() => api.get<any[]>("/supplier/products"));
  const an = useLoad(() => api.get("/supplier/analytics"));
  const inq = useLoad(() => api.get<any[]>("/supplier/inquiries"));
  const rets = useLoad(() => api.get<any[]>("/supplier/returns"));
  const earn = useLoad(() => api.get("/supplier/earnings"));
  const [p, setP] = useState<Record<string, string>>({ product_type: "FERTILIZER", category_slug: "fertilizers", unit: "kg" });
  const [reply, setReply] = useState<Record<number, string>>({});
  const a = useAction(() => { orders.reload(); prods.reload(); inq.reload(); rets.reload(); an.reload(); earn.reload(); });
  const set = (k: string) => (e: { target: { value: string } }) => setP({ ...p, [k]: e.target.value });
  return <><h1>Supplier</h1>
    {an.data && <div className="grid"><Card title="Wallet"><div className="stat">{rupees(an.data.wallet_balance_paise)}</div></Card><Card title="Delivered sales (30 days)"><div className="stat">{rupees(an.data.delivered_sales_paise)}</div></Card>
      <Card title="Rating"><div className="stat">{an.data.rating_count ? an.data.rating_avg : "-"}</div></Card></div>}
    {an.data?.low_stock.length > 0 && <Msg kind="info">Low stock: {an.data.low_stock.map((x: any) => `${x.name} (${x.available})`).join(", ")}</Msg>}
    <div className="tabs">{["orders", "products", "inquiries", "returns", "earnings"].map((k) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{k}</button>)}</div>{a.box}
    {tab === "orders" && <Loading loading={orders.loading} error={orders.error}><Table rows={orders.data || []} cols={[{ head: "Order", cell: (o) => o.order_number }, { head: "Items", cell: (o) => o.items.map((i: any) => `${i.quantity}× ${i.name}`).join(", ") }, { head: "Ship to", cell: (o) => `${o.ship_to.name}, ${o.ship_to.district}` },
      { head: "Total", cell: (o) => rupees(o.total_paise) }, { head: "Status", cell: (o) => <Tag v={o.status} /> }, { head: "", cell: (o) => <div className="row">{ORDER_NEXT[o.status] && <button className="small" onClick={() => a.run(() => api.post(`/supplier/orders/${o.id}/status`, { status: ORDER_NEXT[o.status] }))}>Mark {ORDER_NEXT[o.status].replace(/_/g, " ").toLowerCase()}</button>}
        {o.status === "PLACED" && <button className="small danger" onClick={() => a.run(() => api.post(`/supplier/orders/${o.id}/status`, { status: "REJECTED", note: "Out of stock" }))}>Reject</button>}</div> }]} /></Loading>}
    {tab === "products" && <><Loading loading={prods.loading} error={prods.error}><Table rows={prods.data || []} cols={[{ head: "Product", cell: (x) => x.name }, { head: "Price", cell: (x) => rupees(x.price_paise) }, { head: "Stock", cell: (x) => x.stock }, { head: "Approval", cell: (x) => <Tag v={x.approval_status} /> },
      { head: "", cell: (x) => <div className="row"><button className="small alt" onClick={() => a.run(() => api.post(`/supplier/products/${x.id}/stock`, { delta: 10 }))}>+10</button><button className="small alt" onClick={() => a.run(() => api.post(`/supplier/products/${x.id}/stock`, { delta: -10 }))}>-10</button></div> }]} /></Loading>
      <Card title="Add product (goes to admin for approval)"><Field label="Name"><input value={p.name || ""} onChange={set("name")} /></Field><Field label="Brand"><input value={p.brand || ""} onChange={set("brand")} /></Field>
        <div className="row"><div className="grow"><Field label="Category"><select value={p.category_slug} onChange={set("category_slug")}>{["fertilizers", "crop-protection", "seeds", "micronutrients", "equipment", "irrigation", "organic"].map((c) => <option key={c}>{c}</option>)}</select></Field></div>
          <div className="grow"><Field label="Type"><select value={p.product_type} onChange={set("product_type")}>{["FERTILIZER", "ORGANIC_FERTILIZER", "MICRONUTRIENT", "PESTICIDE", "FUNGICIDE", "INSECTICIDE", "HERBICIDE", "SEED", "TOOL", "EQUIPMENT", "IRRIGATION", "PUMP", "ACCESSORY", "OTHER"].map((c) => <option key={c}>{c}</option>)}</select></Field></div></div>
        <div className="row"><div className="grow"><Field label="Pack size"><input value={p.pack_size || ""} onChange={set("pack_size")} placeholder="50 kg" /></Field></div><div className="grow"><Field label="Price (Rs, GST included)"><input inputMode="decimal" value={p.price || ""} onChange={set("price")} /></Field></div>
          <div className="grow"><Field label="GST %"><input inputMode="decimal" value={p.gst || "5"} onChange={set("gst")} /></Field></div><div className="grow"><Field label="Opening stock"><input inputMode="numeric" value={p.stock || ""} onChange={set("stock")} /></Field></div></div>
        <Field label="Safety information"><textarea value={p.safety_info || ""} onChange={set("safety_info")} /></Field>
        <button disabled={!p.name || !p.pack_size || !p.price || a.busy} onClick={() => a.run(() => api.post("/supplier/products", { name: p.name, brand: p.brand, category_slug: p.category_slug, product_type: p.product_type, pack_size: p.pack_size, price_rupees: Number(p.price), gst_rate_bp: Math.round(Number(p.gst || 5) * 100), safety_info: p.safety_info || "", initial_stock: num(p.stock || "") || 0 }), "Submitted for approval")}>Submit</button></Card></>}
    {tab === "inquiries" && <Loading loading={inq.loading} error={inq.error}>{(inq.data || []).map((i) => <Card key={i.id} title={i.farmer}><p>{i.message}</p>{i.reply ? <p className="muted">Replied: {i.reply}</p> : <div className="row"><div className="grow"><input value={reply[i.id] || ""} onChange={(e) => setReply({ ...reply, [i.id]: val(e) })} aria-label="Reply" /></div><button className="small" onClick={() => a.run(() => api.post(`/supplier/inquiries/${i.id}/reply`, { reply: reply[i.id] }))}>Reply</button></div>}</Card>)}</Loading>}
    {tab === "returns" && <Table rows={rets.data || []} cols={[{ head: "Order", cell: (r) => r.order }, { head: "Reason", cell: (r) => r.reason }, { head: "Status", cell: (r) => <Tag v={r.status} /> }, { head: "", cell: (r) => r.status === "REQUESTED" && <div className="row"><button className="small" onClick={() => a.run(() => api.post(`/supplier/returns/${r.id}/decide`, { approve: true }))}>Approve refund</button><button className="small alt" onClick={() => a.run(() => api.post(`/supplier/returns/${r.id}/decide`, { approve: false, note: "Not eligible" }))}>Decline</button></div> }]} />}
    {tab === "earnings" && earn.data && <Table rows={earn.data.entries} cols={[{ head: "When", cell: (x: any) => when(x.at) }, { head: "Type", cell: (x: any) => x.kind.replace(/_/g, " ").toLowerCase() }, { head: "Ref", cell: (x: any) => x.reference }, { head: "Amount", cell: (x: any) => rupees(x.amount_paise) }]} />}</>;
}

export function Delivery() {
  const jobs = useLoad(() => api.get<any[]>("/delivery/jobs")); const earn = useLoad(() => api.get("/delivery/earnings"));
  const [otp, setOtp] = useState<Record<number, string>>({}); const a = useAction(() => { jobs.reload(); earn.reload(); });
  return <><h1>My deliveries</h1>{earn.data && <div className="grid"><Card title="Deliveries done"><div className="stat">{earn.data.deliveries}</div></Card><Card title="Earned"><div className="stat">{rupees(earn.data.earned_paise)}</div></Card></div>}{a.box}
    <Loading loading={jobs.loading} error={jobs.error}>{(jobs.data || []).map((j) => <Card key={j.id} title={j.order_number} right={<Tag v={j.status} />}>
      <p><b>{j.drop.name}</b> · {j.drop.phone && <a href={`tel:${j.drop.phone}`}>{j.drop.phone}</a>}<br />{j.drop.line1}, {j.drop.district} {j.drop.pincode}</p>
      {j.collect_cash_paise > 0 && <Msg kind="info">Collect cash: {rupees(j.collect_cash_paise)}</Msg>}<p className="muted">{j.items} item(s) · you earn {rupees(j.fee_paise)}{j.due_by ? ` · due ${when(j.due_by)}` : ""}</p>
      <div className="row">{j.status === "ASSIGNED" && <><button onClick={() => a.run(() => api.post(`/delivery/jobs/${j.id}/accept`))}>Accept</button><button className="alt" onClick={() => a.run(() => api.post(`/delivery/jobs/${j.id}/reject`))}>Decline</button></>}
        {j.status === "ACCEPTED" && <button onClick={() => a.run(() => api.post(`/delivery/jobs/${j.id}/pickup`), "Picked up. The farmer has been sent the delivery code.")}>I picked up the parcel</button>}
        {j.status === "PICKED_UP" && <><input style={{ maxWidth: 120 }} inputMode="numeric" maxLength={4} placeholder="4-digit code" value={otp[j.id] || ""} onChange={(e) => setOtp({ ...otp, [j.id]: val(e) })} aria-label="Delivery code" />
          <button onClick={() => a.run(() => api.post(`/delivery/jobs/${j.id}/deliver`, { otp: otp[j.id] }), "Delivered")}>Confirm delivery</button>
          <button className="alt" onClick={() => { const r = prompt("Why could it not be delivered?"); if (r) a.run(() => api.post(`/delivery/jobs/${j.id}/fail`, { reason: r })); }}>Could not deliver</button></>}</div></Card>)}
      {!(jobs.data || []).length && <p className="muted">No active deliveries.</p>}</Loading></>;
}

export function SoilCenterPortal() {
  const b = useLoad(() => api.get<any[]>("/soil-center/bookings")); const [res, setRes] = useState<Record<number, Record<string, string>>>({}); const a = useAction(() => b.reload());
  const NEXT: Record<string, string> = { REQUESTED: "CONFIRMED", CONFIRMED: "SAMPLE_COLLECTED", SAMPLE_COLLECTED: "IN_TESTING" };
  return <><h1>Soil testing requests</h1>{a.box}<Loading loading={b.loading} error={b.error}>{(b.data || []).map((x) => <Card key={x.id} title={x.tracking_code} right={<Tag v={x.status} />}>
    <p>{x.farmer} {x.farmer_phone && `· ${x.farmer_phone}`}<br /><span className="muted">{x.collection.replace("_", " ").toLowerCase()} · preferred {x.preferred_date}</span></p>
    <div className="row">{NEXT[x.status] && <button className="small" onClick={() => a.run(() => api.post(`/soil-center/bookings/${x.id}/status`, { status: NEXT[x.status] }))}>Mark {NEXT[x.status].replace("_", " ").toLowerCase()}</button>}</div>
    {["SAMPLE_COLLECTED", "IN_TESTING"].includes(x.status) && <details><summary>Enter results</summary><div className="row">{["ph", "nitrogen", "phosphorus", "potassium", "organic_carbon", "ec"].map((k) => <div className="grow" key={k}><Field label={k}><input inputMode="decimal" value={res[x.id]?.[k] || ""} onChange={(e) => setRes({ ...res, [x.id]: { ...res[x.id], [k]: val(e) } })} /></Field></div>)}</div>
      <Field label="Interpretation / advice"><textarea value={res[x.id]?.interpretation || ""} onChange={(e) => setRes({ ...res, [x.id]: { ...res[x.id], interpretation: val(e) } })} /></Field>
      <button onClick={() => a.run(() => { const r = res[x.id] || {}; return api.post(`/soil-center/bookings/${x.id}/result`, { ph: num(r.ph || ""), nitrogen: num(r.nitrogen || ""), phosphorus: num(r.phosphorus || ""), potassium: num(r.potassium || ""), organic_carbon: num(r.organic_carbon || ""), ec: num(r.ec || ""), interpretation: r.interpretation }); }, "Report sent to the farmer")}>Send report</button></details>}</Card>)}</Loading></>;
}

export function ExpertPortal() {
  const d = useLoad(() => api.get("/expert/dashboard")); const ap = useLoad(() => api.get<any[]>("/appointments")); const rv = useLoad(() => api.get<any[]>("/expert/disease-reviews"));
  const [n, setN] = useState<Record<number, string>>({}); const a = useAction(() => { ap.reload(); d.reload(); });
  return <><h1>Expert dashboard</h1>{d.data && <div className="grid"><Card title="New requests"><div className="stat">{d.data.pending_requests}</div></Card><Card title="Today"><div className="stat">{d.data.today}</div></Card><Card title="Completed"><div className="stat">{d.data.completed}</div></Card><Card title="Wallet"><div className="stat">{rupees(d.data.wallet)}</div></Card></div>}{a.box}
    <h2>Consultations</h2><Loading loading={ap.loading} error={ap.error}>{(ap.data || []).map((x) => <Card key={x.id} title={`${x.other} - ${when(x.scheduled_at)}`} right={<Tag v={x.status} />}><p>{x.mode}: {x.topic}</p>
      {x.status === "REQUESTED" && <div className="row"><button className="small" onClick={() => a.run(() => api.post(`/appointments/${x.id}/decide`, { action: "CONFIRM" }))}>Accept</button><button className="small alt" onClick={() => a.run(() => api.post(`/appointments/${x.id}/decide`, { action: "DECLINE" }))}>Decline</button></div>}
      {x.status === "CONFIRMED" && <><Field label="Advice for the farmer"><textarea value={n[x.id] || ""} onChange={(e) => setN({ ...n, [x.id]: val(e) })} /></Field><button className="small" onClick={() => a.run(() => api.post(`/appointments/${x.id}/decide`, { action: "COMPLETE", expert_notes: n[x.id] }))}>Complete</button></>}</Card>)}</Loading>
    <h2>Disease photos awaiting review</h2><Table rows={rv.data || []} cols={[{ head: "Crop", cell: (x) => x.crop || "-" }, { head: "Symptoms", cell: (x) => x.symptoms || "-" }, { head: "District", cell: (x) => x.district || "-" }, { head: "Model guess", cell: (x) => x.predictions.map((p: any) => p[0].replace(/_+/g, " ")).join("; ") || "none" }]} /></>;
}

function Kv({ data }: { data: any }) {
  if (data == null) return null;
  if (Array.isArray(data)) return <Table rows={data} cols={Object.keys(data[0] || { value: 1 }).slice(0, 8).map((k) => ({ head: k.replace(/_/g, " "), cell: (r: any) => (typeof r[k] === "object" ? JSON.stringify(r[k]) : String(r[k] ?? "")) }))} />;
  return <div className="grid">{Object.entries(data).map(([k, v]) => <Card key={k} title={k.replace(/_/g, " ")}>{typeof v === "object" ? <Kv data={v} /> : <div className="stat" style={{ fontSize: 20 }}>{k.endsWith("paise") ? rupees(v as number) : String(v)}</div>}</Card>)}</div>;
}

export function Admin({ me }: { me: Me }) {
  const tabs = ["approvals", "users", "orders", "delivery", "products", "tickets", "returns", "devices", "content", "moderation", "reports", ...(me.role === "SUPER_ADMIN" ? ["super"] : [])];
  const [tab, setTab] = useState(me.role === "DISTRICT_MANAGER" ? "approvals" : "approvals");
  const appr = useLoad(() => api.get<any[]>("/admin/approvals"));
  const users = useLoad(() => api.get("/admin/users?size=30"));
  const ord = useLoad(() => api.get("/admin/orders?size=30"));
  const q = useLoad(() => api.get<any[]>("/delivery/queue")); const pr = useLoad(() => api.get<any[]>("/delivery/partners"));
  const prod = useLoad(() => api.get("/admin/products?approval=PENDING"));
  const tix = useLoad(() => api.get<any[]>("/admin/tickets")); const ret = useLoad(() => api.get<any[]>("/admin/returns"));
  const dev = useLoad(() => api.get("/iot/admin/devices")); const rep = useLoad(() => api.get<any[]>("/reports")); const mod = useLoad(() => api.get<any[]>("/community/moderation/reports"));
  const dash = useLoad(() => api.get("/district/dashboard"));
  const [rk, setRk] = useState(""); const [rdata, setRdata] = useState<any>(null); const [pick, setPick] = useState<Record<number, string>>({});
  const a = useAction(() => { appr.reload(); users.reload(); ord.reload(); q.reload(); prod.reload(); tix.reload(); ret.reload(); mod.reload(); });
  const note = (m: string) => prompt(m) || undefined;
  return <><h1>{me.role === "DISTRICT_MANAGER" ? "District" : "Admin"}</h1>{dash.data && <Kv data={dash.data} />}
    <div className="tabs">{tabs.map((k) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{k}</button>)}</div>{a.box}
    {tab === "approvals" && <Loading loading={appr.loading} error={appr.error}>{(appr.data || []).map((u) => <Card key={u.id} title={`${u.name} (${u.role.toLowerCase().replace("_", " ")})`}><p className="muted">{u.mobile} {u.email}</p>
      {u.documents.map((d: any) => <p key={d.id}>{d.type} - <Tag v={d.status} /> <a href={`/api/v1/admin/documents/${d.id}/file`} target="_blank" rel="noreferrer">view</a> <button className="small alt" onClick={() => a.run(() => api.post(`/admin/documents/${d.id}/review`, { approve: true }))}>Verify</button> <button className="small alt" onClick={() => a.run(() => api.post(`/admin/documents/${d.id}/review`, { approve: false, note: note("Reason?") }))}>Reject</button></p>)}
      <div className="row"><button className="small" onClick={() => a.run(() => api.post(`/admin/users/${u.id}/approve`, {}))}>Approve</button><button className="small danger" onClick={() => { const r = note("Reason for rejection"); if (r) a.run(() => api.post(`/admin/users/${u.id}/reject`, { note: r })); }}>Reject</button></div></Card>)}{!(appr.data || []).length && <p className="muted">Nothing waiting.</p>}</Loading>}
    {tab === "users" && <Loading loading={users.loading} error={users.error}>{users.data && <Table rows={users.data.items} cols={[{ head: "Name", cell: (u: any) => u.name }, { head: "Role", cell: (u: any) => u.role }, { head: "Contact", cell: (u: any) => u.mobile || u.email }, { head: "Status", cell: (u: any) => <Tag v={u.status} /> },
      { head: "", cell: (u: any) => <div className="row">{u.status === "ACTIVE" && <button className="small alt" onClick={() => { const r = note("Reason"); if (r) a.run(() => api.post(`/admin/users/${u.id}/suspend`, { note: r })); }}>Suspend</button>}{["SUSPENDED", "BLOCKED"].includes(u.status) && <button className="small" onClick={() => a.run(() => api.post(`/admin/users/${u.id}/reactivate`, {}))}>Reactivate</button>}</div> }]} />}</Loading>}
    {tab === "orders" && <Loading loading={ord.loading} error={ord.error}>{ord.data && <Table rows={ord.data.items} cols={[{ head: "Order", cell: (o: any) => o.order_number }, { head: "Seller", cell: (o: any) => o.supplier_id || "KrishiMitra" }, { head: "District", cell: (o: any) => o.ship_to.district }, { head: "Total", cell: (o: any) => rupees(o.total_paise) }, { head: "Status", cell: (o: any) => <Tag v={o.status} /> }]} />}</Loading>}
    {tab === "delivery" && <><h3>Waiting for a partner</h3><Table rows={q.data || []} cols={[{ head: "Order", cell: (j) => j.order_number }, { head: "To", cell: (j) => `${j.drop.district} ${j.drop.pincode}` }, { head: "Assign", cell: (j) => <div className="row"><select value={pick[j.id] || ""} onChange={(e) => setPick({ ...pick, [j.id]: val(e) })}><option value="">Partner</option>{(pr.data || []).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.active_jobs})</option>)}</select>
      <button className="small" disabled={!pick[j.id]} onClick={() => a.run(() => api.post(`/delivery/${j.id}/assign`, { partner_id: Number(pick[j.id]) }))}>Assign</button></div> }]} /></>}
    {tab === "products" && <Table rows={prod.data?.items || []} cols={[{ head: "Product", cell: (p: any) => p.name }, { head: "Price", cell: (p: any) => rupees(p.price_paise) }, { head: "Seller", cell: (p: any) => p.supplier_id }, { head: "", cell: (p: any) => <div className="row"><button className="small" onClick={() => a.run(() => api.post(`/admin/products/${p.id}/approval`, { approve: true }))}>Approve</button><button className="small danger" onClick={() => a.run(() => api.post(`/admin/products/${p.id}/approval`, { approve: false, note: note("Reason") }))}>Reject</button></div> }]} empty="No products awaiting approval." />}
    {tab === "tickets" && <Table rows={tix.data || []} cols={[{ head: "Subject", cell: (x) => x.subject }, { head: "Category", cell: (x) => x.category }, { head: "Status", cell: (x) => <Tag v={x.status} /> }, { head: "", cell: (x) => <div className="row"><button className="small alt" onClick={() => a.run(() => api.patch(`/admin/tickets/${x.id}`, { status: "IN_PROGRESS" }))}>Start</button><button className="small" onClick={() => { const r = note("Resolution"); if (r) a.run(() => api.patch(`/admin/tickets/${x.id}`, { status: "RESOLVED", resolution: r })); }}>Resolve</button></div> }]} />}
    {tab === "returns" && <Table rows={ret.data || []} cols={[{ head: "Order", cell: (r) => r.order }, { head: "Reason", cell: (r) => r.reason }, { head: "", cell: (r) => <div className="row"><button className="small" onClick={() => a.run(() => api.post(`/admin/returns/${r.id}/decide`, { approve: true }))}>Refund</button><button className="small alt" onClick={() => a.run(() => api.post(`/admin/returns/${r.id}/decide`, { approve: false, note: note("Reason") }))}>Decline</button></div> }]} empty="No return requests." />}
    {tab === "devices" && dev.data && <><Kv data={dev.data.by_connectivity} /><Table rows={dev.data.items} cols={[{ head: "Device", cell: (d: any) => d.uid }, { head: "Owner", cell: (d: any) => d.owner }, { head: "State", cell: (d: any) => <Tag v={d.connectivity} /> }, { head: "Health", cell: (d: any) => <Tag v={d.health} /> }, { head: "Seen", cell: (d: any) => when(d.last_seen) }]} /></>}
    {tab === "moderation" && <Table rows={mod.data || []} cols={[{ head: "Reported", cell: (r) => r.excerpt }, { head: "Reason", cell: (r) => r.reason }, { head: "", cell: (r) => <div className="row"><button className="small danger" onClick={() => a.run(() => api.post(`/community/moderation/reports/${r.id}`, { action: "REMOVE" }))}>Remove</button><button className="small alt" onClick={() => a.run(() => api.post(`/community/moderation/reports/${r.id}`, { action: "DISMISS" }))}>Dismiss</button></div> }]} empty="No reports." />}
    {tab === "content" && <ContentAdmin />}
    {tab === "reports" && <><div className="row">{(rep.data || []).map((r) => <button key={r.key} className="alt small" onClick={() => { setRk(r.key); api.get(`/reports/${r.key}`).then(setRdata); }}>{r.title}</button>)}</div>
      {rdata && <Card title={rdata.title} right={<a href={`/api/v1/reports/${rk}?format=csv`}>Download CSV</a>}><Table rows={rdata.rows} cols={rdata.columns.map((c: string, i: number) => ({ head: c, cell: (r: any[]) => String(r[i]) }))} /></Card>}</>}
    {tab === "super" && <SuperAdmin />}</>;
}

function ContentAdmin() {
  const l = useLoad(() => api.get<any[]>("/admin/content")); const [f, setF] = useState<Record<string, string>>({ kind: "ARTICLE" }); const a = useAction(() => { l.reload(); setF({ kind: "ARTICLE" }); });
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return <><Table rows={l.data || []} cols={[{ head: "Title", cell: (c) => c.title }, { head: "Type", cell: (c) => c.kind }, { head: "Needs check", cell: (c) => (c.needs_verification ? "yes" : "no") }, { head: "", cell: (c) => <button className="small danger" onClick={() => a.run(() => api.del(`/admin/content/${c.id}`))}>Unpublish</button> }]} />
    <Card title="Publish content"><div className="row"><select value={f.kind} onChange={set("kind")}>{["ARTICLE", "GUIDE", "VIDEO", "TRAINING", "SCHEME", "FAQ", "LOAN", "INSURANCE", "ANNOUNCEMENT", "DISEASE", "PEST"].map((k) => <option key={k}>{k}</option>)}</select>
      <select value={f.language || "en"} onChange={set("language")}><option value="en">English</option><option value="hi">हिन्दी</option><option value="mr">मराठी</option></select></div>
      <Field label="Title"><input value={f.title || ""} onChange={set("title")} /></Field><Field label="Summary"><input value={f.summary || ""} onChange={set("summary")} /></Field><Field label="Body"><textarea value={f.body || ""} onChange={set("body")} /></Field><Field label="Official link"><input value={f.url || ""} onChange={set("url")} /></Field>
      <label><input type="checkbox" checked={f.verified === "1"} onChange={() => setF({ ...f, verified: f.verified === "1" ? "0" : "1" })} /> I checked this against the official source</label>{a.box}
      <button disabled={(f.title || "").length < 3} onClick={() => a.run(() => api.post("/admin/content", { kind: f.kind, title: f.title, summary: f.summary, body: f.body || "", url: f.url || undefined, language: f.language || "en", needs_verification: f.verified !== "1", is_published: true }), "Published")}>Publish</button></Card></>;
}

function SuperAdmin() {
  const ov = useLoad(() => api.get("/superadmin/overview")); const roles = useLoad(() => api.get("/superadmin/roles")); const dist = useLoad(() => api.get<any[]>("/superadmin/districts")); const del = useLoad(() => api.get<any[]>("/admin/deletion-requests"));
  const [d, setD] = useState<Record<string, string>>({ status: "PLANNED" }); const [s, setS] = useState<Record<string, string>>({ role: "ADMIN" }); const [b, setB] = useState<Record<string, string>>({}); const [sel, setSel] = useState(""); const [perms, setPerms] = useState<string[] | null>(null);
  const a = useAction(() => { dist.reload(); del.reload(); ov.reload(); });
  const setd = (k: string) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  return <>{ov.data && <Kv data={ov.data} />}
    <h2>Districts</h2><Table rows={dist.data || []} cols={[{ head: "District", cell: (x) => `${x.name}, ${x.state}` }, { head: "Code", cell: (x) => x.code }, { head: "Status", cell: (x) => <select value={x.status} onChange={(e) => a.run(() => api.put(`/superadmin/districts/${x.id}`, { ...x, status: val(e) }))}>{["PLANNED", "ACTIVE", "PAUSED"].map((k) => <option key={k}>{k}</option>)}</select> }]} />
    <Card title="Add district"><div className="row"><div className="grow"><Field label="Name"><input value={d.name || ""} onChange={setd("name")} /></Field></div><div className="grow"><Field label="State"><input value={d.state || ""} onChange={setd("state")} /></Field></div><div className="grow"><Field label="Code"><input value={d.code || ""} onChange={setd("code")} placeholder="MH-XXXX" /></Field></div></div>
      <button onClick={() => a.run(() => api.post("/superadmin/districts", { name: d.name, state: d.state, code: (d.code || "").toUpperCase(), status: d.status }), "Added")}>Add</button></Card>
    <Card title="Create staff account"><div className="row"><div className="grow"><Field label="Name"><input value={s.full_name || ""} onChange={(e) => setS({ ...s, full_name: val(e) })} /></Field></div><div className="grow"><Field label="Email"><input value={s.email || ""} onChange={(e) => setS({ ...s, email: val(e) })} /></Field></div></div>
      <div className="row"><div className="grow"><Field label="Role"><select value={s.role} onChange={(e) => setS({ ...s, role: val(e) })}>{["ADMIN", "DISTRICT_MANAGER", "FINANCE", "DEVELOPER", "FOUNDER", "SUPER_ADMIN"].map((r) => <option key={r}>{r}</option>)}</select></Field></div>
        <div className="grow"><Field label="District (managers)"><select value={s.district_id || ""} onChange={(e) => setS({ ...s, district_id: val(e) })}><option value="">-</option>{(dist.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field></div><div className="grow"><Field label="Temporary password"><input type="password" value={s.password || ""} onChange={(e) => setS({ ...s, password: val(e) })} /></Field></div></div>
      <button onClick={() => a.run(() => api.post("/admin/staff", { ...s, district_id: s.district_id ? Number(s.district_id) : undefined }), "Created")}>Create</button></Card>
    <Card title="Role permissions"><select value={sel} onChange={(e) => { setSel(val(e)); setPerms(roles.data.roles.find((r: any) => r.name === val(e))?.permissions || []); }}><option value="">Choose a role</option>{roles.data?.roles.filter((r: any) => r.name !== "SUPER_ADMIN").map((r: any) => <option key={r.name}>{r.name}</option>)}</select>
      {perms && <><div className="grid">{Object.entries(roles.data.permissions).map(([k, v]: any) => <label key={k}><input type="checkbox" checked={perms.includes(k)} onChange={() => setPerms(perms.includes(k) ? perms.filter((x) => x !== k) : [...perms, k])} /> {k}<br /><span className="muted">{v}</span></label>)}</div>
        <button onClick={() => a.run(() => api.put(`/superadmin/roles/${sel}`, { permissions: perms }), "Saved")}>Save</button></>}</Card>
    <Card title="Send announcement"><Field label="Title"><input value={b.title || ""} onChange={(e) => setB({ ...b, title: val(e) })} /></Field><Field label="Message"><textarea value={b.body || ""} onChange={(e) => setB({ ...b, body: val(e) })} /></Field>
      <button onClick={() => confirm("Send to all active users?") && a.run(async () => { const r = await api.post("/superadmin/broadcast", { title: b.title, body: b.body }); alert(`Sent to ${r.recipients} users`); })}>Send to everyone</button></Card>
    <h2>Deletion requests</h2><Table rows={del.data || []} cols={[{ head: "User", cell: (x) => x.name }, { head: "Reason", cell: (x) => x.reason || "-" }, { head: "", cell: (x) => <div className="row"><button className="small danger" onClick={() => confirm("Anonymise this account?") && a.run(() => api.post(`/admin/deletion-requests/${x.id}/process?approve=true`))}>Approve</button><button className="small alt" onClick={() => a.run(() => api.post(`/admin/deletion-requests/${x.id}/process?approve=false`))}>Decline</button></div> }]} empty="None." /></>;
}

export function Executive({ me }: { me: Me }) {
  const isF = me.role === "FINANCE"; const isDev = me.role === "DEVELOPER";
  const d = useLoad(() => api.get(isF ? "/finance/overview" : isDev ? "/system/overview" : "/founder/overview")); const extra = useLoad(() => (isDev ? api.get("/health") : isF ? api.get("/finance/gst") : api.get("/finance/overview")).catch(() => null));
  return <><h1>{isF ? "Finance" : isDev ? "System" : "Founder overview"}</h1><Loading loading={d.loading} error={d.error}><Kv data={d.data} />{extra.data && <><h2>More</h2><Kv data={extra.data} /></>}</Loading>
    {isF && <p><a href="/api/v1/finance/export/ledger.csv">Download ledger (CSV)</a></p>}</>;
}
