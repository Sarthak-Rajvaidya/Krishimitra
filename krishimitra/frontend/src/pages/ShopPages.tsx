import { useState } from "react";
import { api, rupees, when } from "../api";
import { t } from "../i18n";
import { Link, match } from "../router";
import { Card, Field, Loading, Msg, Table, Tag, num, useAction, useLoad, val } from "../ui";

export function Shop({ path }: { path: string }) {
  const m = match(path, "/market/:id");
  if (m) return <Product id={m.id} />;
  if (path === "/market/compare") return <Compare />;
  return <ShopList />;
}

function ShopList() {
  const cats = useLoad(() => api.get<any[]>("/categories"));
  const [q, setQ] = useState(""); const [cat, setCat] = useState(""); const [sort, setSort] = useState("relevance"); const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<number[]>([]);
  const items = useLoad(() => api.get(`/products?q=${encodeURIComponent(q)}&category=${cat}&sort=${sort}&page=${page}&size=12`), [q, cat, sort, page]);
  const a = useAction();
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-4)));
  return <>
    <h1>{t("nav.market")}</h1>
    <div className="row"><Link className="btn alt" to="/cart">{t("shop.cart")}</Link><Link className="btn alt" to="/wishlist">{t("shop.wish")}</Link><Link className="btn alt" to="/suppliers">Suppliers near me</Link>
      {picked.length >= 2 && <Link className="btn" to={`/market/compare?ids=${picked.join(",")}`}>{t("shop.compare")} ({picked.length})</Link>}</div>
    <Card><div className="row"><div className="grow"><input value={q} onChange={(e) => { setQ(val(e)); setPage(1); }} placeholder={t("common.search")} aria-label={t("common.search")} /></div>
      <select value={cat} onChange={(e) => { setCat(val(e)); setPage(1); }} aria-label="Category"><option value="">All</option>{(cats.data || []).map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}</select>
      <select value={sort} onChange={(e) => setSort(val(e))} aria-label="Sort"><option value="relevance">Name</option><option value="price_asc">Price: low to high</option><option value="price_desc">Price: high to low</option><option value="rating">Best rated</option></select></div></Card>
    {a.box}
    <Loading loading={items.loading} error={items.error}>{items.data && <>
      <div className="grid">{items.data.items.map((p: any) => <Card key={p.id}>
        <Link to={`/market/${p.id}`}><b>{p.name}</b></Link>
        <div className="muted">{p.pack_size} {p.label_verified ? "" : "· label not verified"}</div>
        <div className="stat" style={{ fontSize: 20 }}>{rupees(p.price_paise)}</div>
        <div>{p.in_stock ? (p.low_stock ? <span className="tag warn">few left</span> : <span className="tag good">in stock</span>) : <span className="tag bad">out of stock</span>}</div>
        <div className="row" style={{ marginTop: 8 }}><button className="small" disabled={!p.in_stock} onClick={() => a.run(() => api.post("/cart/items", { product_id: p.id, quantity: 1 }), "Added to cart")}>{t("shop.add")}</button>
          <label style={{ margin: 0 }}><input type="checkbox" checked={picked.includes(p.id)} onChange={() => toggle(p.id)} /> {t("shop.compare")}</label></div></Card>)}</div>
      <div className="row"><button className="alt" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.back")}</button><span>Page {page}</span><button className="alt" disabled={page * 12 >= items.data.total} onClick={() => setPage(page + 1)}>Next</button></div></>}</Loading>
  </>;
}

function Compare() {
  const ids = (location.hash.split("ids=")[1] || "").split("&")[0];
  const d = useLoad(() => api.get<any[]>(`/products/compare?ids=${ids}`), [ids]);
  const rows: [string, (p: any) => any][] = [["Price", (p) => rupees(p.price_paise)], ["Pack", (p) => p.pack_size], ["Price per unit", (p) => (p.unit_price_paise ? `${rupees(p.unit_price_paise)}/${p.unit}` : "-")], ["Brand", (p) => p.brand || "-"],
    ["Rating", (p) => (p.rating_count ? `${p.rating_avg} (${p.rating_count})` : "-")], ["In stock", (p) => (p.in_stock ? "Yes" : "No")], ["Label verified", (p) => (p.label_verified ? "Yes" : "No")], ["Safety", (p) => p.safety_info || "-"]];
  return <><p><Link to="/market">{t("common.back")}</Link></p><h1>{t("shop.compare")}</h1>
    <Loading loading={d.loading} error={d.error}><div className="scroll"><table><thead><tr><th></th>{(d.data || []).map((p) => <th key={p.id}><Link to={`/market/${p.id}`}>{p.name}</Link></th>)}</tr></thead>
      <tbody>{rows.map(([l, f]) => <tr key={l}><th>{l}</th>{(d.data || []).map((p) => <td key={p.id}>{f(p)}</td>)}</tr>)}</tbody></table></div></Loading></>;
}

function Product({ id }: { id: string }) {
  const p = useLoad(() => api.get(`/products/${id}`), [id]);
  const rv = useLoad(() => api.get<any[]>(`/ratings?target_type=PRODUCT&target_id=${id}`), [id]);
  const [qty, setQty] = useState("1"); const [stars, setStars] = useState("5"); const [text, setText] = useState(""); const [ask, setAsk] = useState("");
  const a = useAction(() => rv.reload());
  return <><p><Link to="/market">{t("common.back")}</Link></p>
    <Loading loading={p.loading} error={p.error}>{p.data && <>
      <h1>{p.data.name}</h1>
      <Card><div className="stat">{rupees(p.data.price_paise)} <span className="muted" style={{ fontSize: 15 }}>{p.data.pack_size}</span></div>
        <p>Sold by <b>{p.data.supplier_name}</b> {p.data.rating_count ? `· ${p.data.rating_avg}/5 (${p.data.rating_count})` : ""}</p>
        <p>{p.data.description}</p>{p.data.safety_info && <Msg kind="info">{p.data.safety_info}</Msg>}
        {!p.data.label_verified && <p className="muted">Label details for this product have not been verified by KrishiMitra. Read the pack label before use.</p>}
        <div className="row"><input style={{ width: 80 }} inputMode="numeric" value={qty} onChange={(e) => setQty(val(e))} aria-label="Quantity" />
          <button disabled={!p.data.in_stock} onClick={() => a.run(() => api.post("/cart/items", { product_id: p.data.id, quantity: num(qty) || 1 }), "Added to cart")}>{t("shop.add")}</button>
          <button className="alt" onClick={() => a.run(() => api.put(`/wishlist/${p.data.id}`), "Saved")}>{t("shop.wish")}</button></div>{a.box}</Card>
      {p.data.supplier_id && <Card title="Ask the seller"><textarea value={ask} onChange={(e) => setAsk(val(e))} /><button disabled={ask.length < 3} onClick={() => a.run(() => api.post("/inquiries", { supplier_id: p.data.supplier_id, product_id: p.data.id, message: ask }), "Sent. The seller will reply here and in your alerts.")}>{t("common.submit")}</button></Card>}
      <h2>Reviews</h2>
      <Loading loading={rv.loading} error={rv.error}>{(rv.data || []).map((r) => <p key={r.id}>{"★".repeat(r.rating)} {r.comment} <span className="muted">- {r.by}{r.verified ? " · verified buyer" : ""}</span></p>)}{!(rv.data || []).length && <p className="muted">No reviews yet.</p>}</Loading>
      <Card title="Write a review"><select value={stars} onChange={(e) => setStars(val(e))}>{[5, 4, 3, 2, 1].map((n) => <option key={n}>{n}</option>)}</select><textarea value={text} onChange={(e) => setText(val(e))} />
        <button onClick={() => a.run(() => api.post("/ratings", { target_type: "PRODUCT", target_id: p.data.id, rating: Number(stars), comment: text }), "Thank you")}>{t("common.submit")}</button></Card></>}</Loading></>;
}

export function Wishlist() {
  const w = useLoad(() => api.get<any[]>("/wishlist"));
  const a = useAction(() => w.reload());
  return <><h1>{t("shop.wish")}</h1>{a.box}<Loading loading={w.loading} error={w.error}><Table rows={w.data || []} cols={[{ head: "Product", cell: (p) => <Link to={`/market/${p.id}`}>{p.name}</Link> }, { head: t("common.price"), cell: (p) => rupees(p.price_paise) },
    { head: "", cell: (p) => <div className="row"><button className="small" onClick={() => a.run(() => api.post("/cart/items", { product_id: p.id, quantity: 1 }), "Added")}>{t("shop.add")}</button><button className="small alt" onClick={() => a.run(() => api.del(`/wishlist/${p.id}`))}>x</button></div> }]} /></Loading></>;
}

export function Suppliers() {
  const [d, setD] = useState("");
  const s = useLoad(() => api.get<any[]>(`/suppliers?district=${encodeURIComponent(d)}`), [d]);
  return <><p><Link to="/market">{t("common.back")}</Link></p><h1>Suppliers</h1><Field label={t("farm.district")}><input value={d} onChange={(e) => setD(val(e))} /></Field>
    <Loading loading={s.loading} error={s.error}><Table rows={s.data || []} cols={[{ head: "Shop", cell: (x) => <Link to={`/market?supplier=${x.id}`}>{x.shop_name}</Link> }, { head: "Place", cell: (x) => [x.village, x.district].filter(Boolean).join(", ") }, { head: "Sells", cell: (x) => x.categories || "-" },
      { head: "Rating", cell: (x) => (x.rating_count ? `${x.rating_avg} (${x.rating_count})` : "-") }, { head: "Hours", cell: (x) => x.hours || "-" }]} /></Loading></>;
}

export function Cart() {
  const [promo, setPromo] = useState(""); const [addr, setAddr] = useState(""); const [mode, setMode] = useState("COD"); const [share, setShare] = useState(false);
  const addrs = useLoad(() => api.get<any[]>("/addresses"));
  const cart = useLoad(() => api.get(`/cart?promo=${encodeURIComponent(promo)}${addr ? "&pincode=" + (addrs.data?.find((x) => String(x.id) === addr)?.pincode || "") : ""}`), [promo, addr, addrs.data]);
  const [done, setDone] = useState<any>(null);
  const [n, setN] = useState<Record<string, string>>({});
  const a = useAction(() => { cart.reload(); addrs.reload(); });
  const key = useState(() => crypto.randomUUID?.() || String(Date.now()))[0];
  if (done) return <><h1>Order placed</h1><Msg kind="ok">Your order was split by seller. You will see each one in Orders.</Msg>{done.orders.map((o: any) => <p key={o.id}>{o.order_number} - {rupees(o.total_paise)}</p>)}<Link className="btn" to="/orders">{t("nav.orders")}</Link></>;
  return <>
    <h1>{t("shop.cart")}</h1>
    <Loading loading={cart.loading} error={cart.error}>{cart.data && (cart.data.items.length ? <>
      <Table rows={cart.data.items} cols={[{ head: "Item", cell: (i: any) => i.name }, { head: "Qty", cell: (i: any) => <input style={{ width: 70 }} inputMode="numeric" defaultValue={i.quantity} onBlur={(e) => Number(e.target.value) !== i.quantity && a.run(() => api.put(`/cart/items/${i.id}`, { quantity: Number(e.target.value) || 1 }))} /> },
        { head: "Total", cell: (i: any) => rupees(i.line_total_paise) }, { head: "", cell: (i: any) => <button className="small alt" onClick={() => a.run(() => api.del(`/cart/items/${i.id}`))}>x</button> }]} />
      <Card><p>Items: {rupees(cart.data.subtotal_paise)}</p>{cart.data.discount_paise > 0 && <p>Discount: -{rupees(cart.data.discount_paise)}</p>}<p>Delivery: {cart.data.delivery_fee_applies ? rupees(cart.data.delivery_fee_paise) : "shown after you pick an address"}</p>
        <p><b>Total: {rupees(cart.data.total_paise)}</b> <span className="muted">(GST included)</span></p>
        <Field label="Promo code"><input value={promo} onChange={(e) => setPromo(val(e).toUpperCase())} /></Field></Card>
      <Card title={t("shop.address")}>
        <Field label=""><select value={addr} onChange={(e) => setAddr(val(e))}><option value="">Choose</option>{(addrs.data || []).map((x) => <option key={x.id} value={x.id}>{x.line1}, {x.district} {x.pincode}</option>)}</select></Field>
        <details><summary>Add new address</summary>
          {["line1", "village", "district", "state", "pincode"].map((k) => <Field key={k} label={k}><input value={n[k] || ""} onChange={(e) => setN({ ...n, [k]: val(e) })} /></Field>)}
          <button className="alt" onClick={() => a.run(async () => { const r = await api.post("/addresses", { ...n, label: "Home" }); setAddr(String(r.id)); setN({}); })}>{t("common.save")}</button></details></Card>
      <Card title="Payment"><label><input type="radio" checked={mode === "COD"} onChange={() => setMode("COD")} /> {t("shop.cod")}</label><label><input type="radio" checked={mode === "WALLET"} onChange={() => setMode("WALLET")} /> {t("shop.wallet")} (<Link to="/wallet">{t("wallet.add")}</Link>)</label>
        <label><input type="checkbox" checked={share} onChange={() => setShare(!share)} /> Let the seller see the crop advice behind my order</label></Card>
      {a.box}<button disabled={!addr || a.busy} onClick={() => a.run(async () => setDone(await api.post("/checkout", { address_id: Number(addr), payment_mode: mode, promo_code: promo || undefined, share_advisory: share }, { "Idempotency-Key": key })))}>{t("shop.checkout")}</button>
    </> : <p className="muted">Your cart is empty. <Link to="/market">{t("nav.market")}</Link></p>)}</Loading></>;
}

export function Orders() {
  const o = useLoad(() => api.get<any[]>("/orders"));
  const a = useAction(() => o.reload());
  const [reason, setReason] = useState("");
  return <><h1>{t("nav.orders")}</h1>{a.box}
    <Loading loading={o.loading} error={o.error}>{(o.data || []).map((x) => <Card key={x.id} title={x.order_number} right={<Tag v={x.status} />}>
      <p className="muted">{when(x.placed_at)} · {x.payment_mode} · {rupees(x.total_paise)}</p>
      {x.items.map((i: any) => <div key={i.sku}>{i.quantity} × {i.name}</div>)}
      {x.delivery?.otp && <Msg kind="info">Delivery code: <b style={{ fontSize: 22 }}>{x.delivery.otp}</b>. Tell it to the delivery partner only when you receive your parcel.</Msg>}
      <details><summary>Timeline</summary>{x.timeline.map((h: any, i: number) => <div key={i} className="muted">{when(h.at)} - {h.status.replace(/_/g, " ").toLowerCase()} {h.note || ""}</div>)}</details>
      <div className="row" style={{ marginTop: 8 }}>
        {["PLACED", "CONFIRMED"].includes(x.status) && <button className="small danger" onClick={() => a.run(() => api.post(`/orders/${x.id}/cancel`))}>{t("common.cancel")}</button>}
        {x.status === "DELIVERED" && <><input style={{ maxWidth: 260 }} placeholder="Return reason" value={reason} onChange={(e) => setReason(val(e))} /><button className="small alt" disabled={reason.length < 5} onClick={() => a.run(() => api.post(`/orders/${x.id}/return`, { reason }), "Return requested")}>Return</button></>}
        {x.supplier_id && x.status === "DELIVERED" && <Link className="btn small alt" to={`/market`}>Rate seller from the product page</Link>}</div></Card>)}</Loading></>;
}
