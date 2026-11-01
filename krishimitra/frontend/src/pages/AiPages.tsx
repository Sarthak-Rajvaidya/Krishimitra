import { useRef, useState } from "react";
import { api, rupees, when } from "../api";
import { t } from "../i18n";
import { Link } from "../router";
import { Card, Field, Loading, Msg, Table, Tag, useAction, useLoad, val } from "../ui";
import { canListen, canSpeak, listen, speak } from "../voice";

export function Doctor() {
  const list = useLoad(() => api.get<any[]>("/crop/diagnoses"));
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [res, setRes] = useState<any>(null);
  const [recs, setRecs] = useState<any>(null);
  const a = useAction(() => list.reload());
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const send = () => a.run(async () => {
    const fd = new FormData(); fd.append("image", file!);
    for (const k of ["crop", "crop_stage", "plant_part", "symptoms", "district"]) if (f[k]) fd.append(k, f[k]);
    setRes(await api.upload("/crop/diagnose", fd)); setRecs(null);
  });
  return <>
    <h1>{t("doctor.title")}</h1>
    <Msg kind="info">{t("doctor.note")}</Msg>
    <Card>
      <Field label={t("doctor.upload")}><input type="file" accept="image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
      <div className="row"><div className="grow"><Field label="Crop"><input value={f.crop || ""} onChange={set("crop")} /></Field></div>
        <div className="grow"><Field label="Plant part"><select value={f.plant_part || ""} onChange={set("plant_part")}><option value="">Choose</option><option>leaf</option><option>stem</option><option>fruit</option><option>root</option></select></Field></div></div>
      <Field label="What do you see?"><textarea value={f.symptoms || ""} onChange={set("symptoms")} placeholder="Spots, yellowing, insects, since when..." /></Field>
      {a.box}<button disabled={!file || a.busy} onClick={send}>{a.busy ? t("common.loading") : t("common.submit")}</button>
    </Card>
    {res && <Card title="Result">
      {res.model_note && <Msg kind="info">{res.model_note}</Msg>}
      {res.uncertain && <Msg kind="info">The model is not sure about this photo. Treat the options below as leads only.</Msg>}
      {res.predictions.map((p: any, i: number) => <p key={i}>{i + 1}. {p.label.replace(/_+/g, " ")} <span className="muted">(score {p.score})</span></p>)}
      <p className="muted">{res.score_note}</p>
      <div className="row"><button onClick={() => api.post(`/recommendations/diagnosis/${res.id}`).then(setRecs).catch((e) => a.run(async () => { throw e; }))}>See product options</button>
        <Link className="btn alt" to={`/experts?diagnosis=${res.id}`}>Ask an expert</Link>
        <button className="alt" onClick={async () => { const s = await api.post(`/crop/diagnoses/${res.id}/share`); a.run(async () => { await navigator.clipboard?.writeText(`${location.origin}/api/v1/shared/${s.token}`); }, "Link copied. It expires in 72 hours."); }}>Share with expert</button></div>
    </Card>}
    {recs && <Card title="Options">
      {recs.notes.map((n: string, i: number) => <Msg key={i} kind="info">{n}</Msg>)}
      {recs.candidates.map((c: any) => <div key={c.product_id} style={{ borderTop: "1px solid #ddd", padding: "8px 0" }}>
        <b>{c.name}</b> {c.included ? <Tag v="APPROVED" /> : <span className="tag warn">not suggested</span>}
        <p className="muted">{c.included ? c.uncertainty : c.exclusion_reason}</p>
        {c.included && <div className="row"><span>{rupees(c.pack.price_paise)}</span><button className="small" onClick={() => a.run(() => api.post("/cart/items", { product_id: c.product_id, quantity: 1, recommendation_id: c.recommendation_id }), "Added to cart")}>{t("shop.add")}</button>
          <button className="small alt" onClick={() => api.get(`/recommendations/${c.recommendation_id}/offers`).then((o) => alert(o.offers.map((x: any) => `${x.seller}: ${rupees(x.price_paise)} (${x.pack_size})`).join("\n")))}>Compare sellers</button></div>}
      </div>)}
      <p className="muted">{recs.disclaimer}</p></Card>}
    <h2>History</h2>
    <Loading loading={list.loading} error={list.error}><Table rows={list.data || []} cols={[{ head: "Date", cell: (d) => when(d.created_at) }, { head: "Crop", cell: (d) => d.crop || "-" }, { head: "Top result", cell: (d) => d.predictions[0]?.label.replace(/_+/g, " ") || "-" }, { head: t("common.status"), cell: (d) => <Tag v={d.status} /> }]} /></Loading>
  </>;
}

export function Assistant() {
  const [cid, setCid] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<{ role: string; content: string; citations?: any[]; grounded?: boolean }[]>([]);
  const [q, setQ] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [rec, setRec] = useState(false);
  const sug = useLoad(() => api.get<string[]>(`/advisory/suggestions?lang=${localStorage.getItem("km_lang") || "en"}`));
  const end = useRef<HTMLDivElement>(null);
  const ask = async (text: string) => {
    if (!text.trim()) return;
    setBusy(true); setErr(""); setQ(""); setMsgs((m) => [...m, { role: "user", content: text }]);
    try {
      let id = cid; if (!id) { id = (await api.post("/advisory/conversations", {})).id; setCid(id); }
      const r = await api.post(`/advisory/conversations/${id}/messages`, { message: text });
      setMsgs((m) => [...m, { role: "assistant", content: r.content, citations: r.citations, grounded: r.grounded }]);
      if (canSpeak() && localStorage.getItem("km_autoread") === "1") speak(r.content);
    } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); setTimeout(() => end.current?.scrollIntoView(), 50); }
  };
  return <>
    <h1>{t("nav.assistant")}</h1>
    <Card>
      <div className="chat">{msgs.length === 0 && <p className="muted">{t("assistant.ask")}</p>}
        {msgs.map((m, i) => <div key={i} className={"bubble " + (m.role === "user" ? "me" : "bot")}>{m.content}
          {m.role === "assistant" && <>{m.grounded === false && <div className="muted">Not backed by a verified source.</div>}
            {m.citations?.map((c: any) => <div key={c.n} className="muted">[{c.n}] {c.title}{c.page ? `, p.${c.page}` : ""}</div>)}
            {canSpeak() && <button className="small alt" onClick={() => speak(m.content)}>{t("assistant.listen")}</button>}</>}</div>)}
        <div ref={end} /></div>
      <Msg>{err}</Msg>
      <div className="row"><div className="grow"><input value={q} onChange={(e) => setQ(val(e))} onKeyDown={(e) => e.key === "Enter" && !busy && ask(q)} placeholder={t("assistant.ask")} aria-label={t("assistant.ask")} /></div>
        {canListen() && <button className="alt" disabled={rec} onClick={() => { setRec(true); listen((s) => setQ(s), () => setRec(false)); }}>{rec ? "..." : t("assistant.speak")}</button>}
        <button disabled={busy || !q.trim()} onClick={() => ask(q)}>{t("assistant.send")}</button></div>
    </Card>
    {!msgs.length && <Card title="Try asking">{(sug.data || []).map((s) => <p key={s}><a href="#/assistant" onClick={(e) => { e.preventDefault(); ask(s); }}>{s}</a></p>)}</Card>}
    <p className="muted">Answers come from the documents in our knowledge base. Check with an expert before spraying or applying anything.</p>
  </>;
}
