import { rupees } from "./api";
import { t, setLang } from "./i18n";

describe("helpers", () => {
  it("formats paise as rupees", () => {
    expect(rupees(12345)).toContain("123.45");
    expect(rupees(null)).toBe("-");
  });
  it("falls back to English for a missing translation", () => {
    setLang("mr");
    expect(t("definitely.not.a.key")).toBe("definitely.not.a.key");
    setLang("en");
  });
  it("has the same keys in every language for the core menu", () => {
    for (const l of ["hi", "mr"] as const) { setLang(l); expect(t("nav.home")).not.toBe("nav.home"); }
    setLang("en");
  });
});
