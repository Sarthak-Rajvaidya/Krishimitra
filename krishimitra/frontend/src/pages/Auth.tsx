import { useState } from "react";
import { api } from "../api";
import { Me, useAuth } from "../auth";
import { t } from "../i18n";
import { Field, Msg, useAction, val } from "../ui";

type Mode = "login" | "otp" | "register" | "verify" | "forgot" | "reset";
const ROLES = [["FARMER", "Farmer"], ["EXPERT", "Agriculture expert"], ["SUPPLIER", "Supplier / shop"], ["DELIVERY", "Delivery partner"], ["SOIL_CENTER", "Soil testing centre"]];

export default function Auth() {
  const { setMe } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [id, setId] = useState(""); const [pw, setPw] = useState(""); const [code, setCode] = useState(""); const [newPw, setNewPw] = useState("");
  const [name, setName] = useState(""); const [role, setRole] = useState("FARMER"); const [lang, setLang] = useState("en");
  const [p, setP] = useState<Record<string, string>>({});
  const [hint, setHint] = useState("");
  const a = useAction();
  const set = (k: string) => (e: { target: { value: string } }) => setP({ ...p, [k]: e.target.value });
  const enter = (r: { user: Me }) => { setMe(r.user); window.location.hash = r.user.portal || "/"; };

  const sendCode = (purpose: "LOGIN" | "VERIFY") => a.run(async () => {
    const r = await api.post("/auth/otp/request", { identifier: id, purpose }); setHint(r.dev_code ? `Development code: ${r.dev_code}` : "Code sent. Check your phone or email.");
  });

  const register = () => a.run(async () => {
    const profile: Record<string, unknown> = { ...p };
    for (const k of ["experience_years", "farm_size_acres"]) if (p[k]) profile[k] = Number(p[k]);
    if (p.fee_rupees) { profile.fee_paise = Number(p.fee_rupees) * 100; delete profile.fee_rupees; }
    if (p.account_no) { profile.bank = { account_no: p.account_no, ifsc: p.ifsc, holder: p.holder }; delete profile.account_no; delete profile.ifsc; delete profile.holder; }
    const isMail = id.includes("@");
    const r = await api.post("/auth/register", { role, full_name: name, mobile: isMail ? undefined : id, email: isMail ? id : undefined, password: pw, language: lang, profile });
    setHint(r.dev_code ? `Development code: ${r.dev_code}` : "We sent a code to verify your contact."); setMode("verify");
  });

  return (
    <div className="auth card">
      <h1>KrishiMitra</h1>
      {(mode === "login" || mode === "otp") && <>
        <Field label={t("auth.mobile")}><input value={id} onChange={(e) => setId(val(e))} autoComplete="username" inputMode="email" /></Field>
        {mode === "login" ? <Field label={t("auth.password")}><input type="password" value={pw} onChange={(e) => setPw(val(e))} autoComplete="current-password" /></Field>
          : <><div className="row" style={{ marginTop: 8 }}><button className="alt" onClick={() => sendCode("LOGIN")} disabled={!id}>{t("auth.send")}</button></div>
            <Field label={t("auth.code")}><input value={code} onChange={(e) => setCode(val(e))} inputMode="numeric" maxLength={8} /></Field></>}
        <Msg kind="info">{hint}</Msg>{a.box}
        <div className="row" style={{ marginTop: 12 }}>
          <button disabled={a.busy} onClick={() => a.run(async () => enter(mode === "login" ? await api.post("/auth/login", { identifier: id, password: pw }) : await api.post("/auth/login/otp", { identifier: id, code })))}>{t("common.login")}</button>
          <button className="alt" onClick={() => { setMode(mode === "login" ? "otp" : "login"); setHint(""); }}>{mode === "login" ? t("auth.otp") : t("auth.password")}</button>
        </div>
        <p><a href="#/" onClick={(e) => { e.preventDefault(); setMode("forgot"); setHint(""); }}>{t("auth.forgot")}</a> · <a href="#/" onClick={(e) => { e.preventDefault(); setMode("register"); setHint(""); }}>{t("common.register")}</a></p>
      </>}

      {mode === "register" && <>
        <Field label={t("auth.role")}><select value={role} onChange={(e) => { setRole(val(e)); setP({}); }}>{ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label={t("auth.name")}><input value={name} onChange={(e) => setName(val(e))} /></Field>
        <Field label={t("auth.mobile")}><input value={id} onChange={(e) => setId(val(e))} /></Field>
        <Field label={t("auth.password")}><input type="password" value={pw} onChange={(e) => setPw(val(e))} autoComplete="new-password" /></Field>
        <p className="muted">At least 8 characters with a letter and a number.</p>
        <Field label={t("common.language")}><select value={lang} onChange={(e) => setLang(val(e))}><option value="en">English</option><option value="hi">हिन्दी</option><option value="mr">मराठी</option></select></Field>
        <Field label="District"><input value={p.district || ""} onChange={set("district")} /></Field>
        <Field label="State"><input value={p.state || ""} onChange={set("state")} /></Field>
        {role === "FARMER" && <>
          <Field label="Village"><input value={p.village || ""} onChange={set("village")} /></Field>
          <Field label="Main crops"><input value={p.primary_crops || ""} onChange={set("primary_crops")} placeholder="e.g. tomato, onion" /></Field>
          <Field label="Farm size (acres)"><input inputMode="decimal" value={p.farm_size_acres || ""} onChange={set("farm_size_acres")} /></Field></>}
        {role === "EXPERT" && <>
          <Field label="Qualification"><input value={p.qualification || ""} onChange={set("qualification")} /></Field>
          <Field label="Specialization (comma separated)"><input value={p.specialization || ""} onChange={set("specialization")} /></Field>
          <Field label="Years of experience"><input inputMode="numeric" value={p.experience_years || ""} onChange={set("experience_years")} /></Field>
          <Field label="Consultation fee (Rs)"><input inputMode="numeric" value={p.fee_rupees || ""} onChange={set("fee_rupees")} /></Field></>}
        {role === "SUPPLIER" && <>
          <Field label="Shop / business name"><input value={p.shop_name || ""} onChange={set("shop_name")} /></Field>
          <Field label="GST number (if any)"><input value={p.gst_no || ""} onChange={set("gst_no")} /></Field>
          <Field label="Address"><input value={p.address || ""} onChange={set("address")} /></Field>
          <Field label="Pincode"><input value={p.pincode || ""} onChange={set("pincode")} maxLength={6} /></Field>
          <Field label="Bank account (for payouts)"><input value={p.account_no || ""} onChange={set("account_no")} /></Field>
          <Field label="IFSC"><input value={p.ifsc || ""} onChange={set("ifsc")} /></Field>
          <Field label="Account holder"><input value={p.holder || ""} onChange={set("holder")} /></Field></>}
        {role === "DELIVERY" && <>
          <Field label="Vehicle type"><select value={p.vehicle_type || ""} onChange={set("vehicle_type")}><option value="">Choose</option><option>BIKE</option><option>AUTO</option><option>PICKUP</option><option>TRUCK</option></select></Field>
          <Field label="Vehicle number"><input value={p.vehicle_number || ""} onChange={set("vehicle_number")} /></Field>
          <Field label="Driving licence number"><input value={p.licence_number || ""} onChange={set("licence_number")} /></Field>
          <Field label="Pincodes you serve (comma separated)"><input value={p.service_pincodes || ""} onChange={set("service_pincodes")} /></Field></>}
        {role === "SOIL_CENTER" && <>
          <Field label="Centre name"><input value={p.name || ""} onChange={set("name")} /></Field>
          <Field label="Address"><input value={p.address || ""} onChange={set("address")} /></Field>
          <Field label="Pincode"><input value={p.pincode || ""} onChange={set("pincode")} maxLength={6} /></Field></>}
        {role !== "FARMER" && <Msg kind="info">After you verify your contact, an admin reviews your account. Upload your documents from Settings so approval is quick.</Msg>}
        {a.box}
        <div className="row" style={{ marginTop: 12 }}><button disabled={a.busy} onClick={register}>{t("common.register")}</button><button className="alt" onClick={() => setMode("login")}>{t("common.back")}</button></div>
      </>}

      {mode === "verify" && <>
        <p>Enter the code we sent to <b>{id}</b>.</p><Msg kind="info">{hint}</Msg>
        <Field label={t("auth.code")}><input value={code} onChange={(e) => setCode(val(e))} inputMode="numeric" maxLength={8} /></Field>{a.box}
        <div className="row" style={{ marginTop: 12 }}>
          <button disabled={a.busy} onClick={() => a.run(async () => enter(await api.post("/auth/verify", { identifier: id, code })))}>{t("auth.verify")}</button>
          <button className="alt" onClick={() => sendCode("VERIFY")}>{t("auth.send")}</button></div>
      </>}

      {(mode === "forgot" || mode === "reset") && <>
        <Field label={t("auth.mobile")}><input value={id} onChange={(e) => setId(val(e))} /></Field>
        {mode === "forgot" ? <button disabled={a.busy || !id} onClick={() => a.run(async () => { const r = await api.post("/auth/password/forgot", { identifier: id }); setHint(r.dev_code ? `Development code: ${r.dev_code}` : r.message); setMode("reset"); })}>{t("auth.send")}</button>
          : <><Msg kind="info">{hint}</Msg>
            <Field label={t("auth.code")}><input value={code} onChange={(e) => setCode(val(e))} inputMode="numeric" /></Field>
            <Field label="New password"><input type="password" value={newPw} onChange={(e) => setNewPw(val(e))} autoComplete="new-password" /></Field>
            <button disabled={a.busy} onClick={() => a.run(async () => { await api.post("/auth/password/reset", { identifier: id, code, new_password: newPw }); setMode("login"); setHint("Password changed. Sign in with the new password."); })}>{t("common.submit")}</button></>}
        {a.box}<p><a href="#/" onClick={(e) => { e.preventDefault(); setMode("login"); }}>{t("common.back")}</a></p>
      </>}
    </div>
  );
}
