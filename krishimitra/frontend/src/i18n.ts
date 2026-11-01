// Small dictionary-based translation. Anything not listed falls back to English.
// Hindi and Marathi cover the menus, buttons and main headings; they should be reviewed by a native speaker before launch.
export type Lang = "en" | "hi" | "mr";
type Dict = Record<string, string>;

const en: Dict = {
  "nav.home": "Home", "nav.farms": "My Farms", "nav.crops": "Crops", "nav.soil": "Soil", "nav.doctor": "Crop Doctor", "nav.assistant": "Ask KrishiMitra",
  "nav.market": "Shop", "nav.orders": "Orders", "nav.machines": "Rent Machines", "nav.devices": "Devices", "nav.experts": "Experts", "nav.community": "Community",
  "nav.learn": "Learn", "nav.schemes": "Schemes", "nav.wallet": "Wallet", "nav.support": "Help", "nav.settings": "Settings", "nav.notifications": "Alerts",
  "nav.weather": "Weather", "common.save": "Save", "common.cancel": "Cancel", "common.add": "Add", "common.delete": "Delete", "common.edit": "Edit", "common.search": "Search",
  "common.loading": "Loading...", "common.none": "Nothing here yet.", "common.back": "Back", "common.submit": "Submit", "common.logout": "Sign out", "common.login": "Sign in",
  "common.register": "Create account", "common.yes": "Yes", "common.no": "No", "common.language": "Language", "common.price": "Price", "common.status": "Status",
  "auth.mobile": "Mobile number or email", "auth.password": "Password", "auth.forgot": "Forgot password?", "auth.otp": "Sign in with a code instead", "auth.code": "Code",
  "auth.verify": "Verify", "auth.name": "Full name", "auth.role": "I am a", "auth.send": "Send code",
  "home.welcome": "Welcome", "home.crops": "Active crops", "home.orders": "Orders in progress", "home.wallet": "Wallet", "home.alerts": "Unread alerts",
  "home.advice": "Advice for you", "home.harvest": "Harvest soon", "home.appointments": "Upcoming consultations",
  "farm.add": "Add farm", "farm.name": "Farm name", "farm.area": "Area (acres)", "farm.village": "Village", "farm.district": "District", "farm.fields": "Fields",
  "crop.add": "Add crop", "crop.sowing": "Sowing date", "crop.harvest": "Expected harvest", "crop.records": "Records", "crop.profit": "Profit / loss",
  "doctor.title": "Check my crop", "doctor.upload": "Take or choose a clear photo of the affected leaf", "doctor.note": "This is a guide only. Confirm with an expert before spraying anything.",
  "assistant.ask": "Ask a question about your crop", "assistant.speak": "Speak", "assistant.listen": "Read aloud", "assistant.send": "Send",
  "shop.add": "Add to cart", "shop.cart": "Cart", "shop.checkout": "Place order", "shop.compare": "Compare", "shop.wish": "Save for later", "shop.cod": "Cash on delivery",
  "shop.wallet": "Pay from wallet", "shop.address": "Delivery address",
  "iot.pump": "Water pump", "iot.on": "Start", "iot.off": "Stop", "iot.auto": "Automatic", "iot.manual": "Manual", "iot.moisture": "Soil moisture", "iot.open": "Open monitoring site",
  "wallet.balance": "Balance", "wallet.add": "Add money", "support.new": "Raise a ticket", "settings.privacy": "Privacy", "settings.delete": "Request account deletion",
};

const hi: Dict = {
  "nav.home": "होम", "nav.farms": "मेरे खेत", "nav.crops": "फसलें", "nav.soil": "मिट्टी", "nav.doctor": "फसल डॉक्टर", "nav.assistant": "कृषिमित्र से पूछें",
  "nav.market": "खरीदारी", "nav.orders": "ऑर्डर", "nav.machines": "मशीन किराये पर", "nav.devices": "उपकरण", "nav.experts": "विशेषज्ञ", "nav.community": "समुदाय",
  "nav.learn": "सीखें", "nav.schemes": "योजनाएँ", "nav.wallet": "वॉलेट", "nav.support": "सहायता", "nav.settings": "सेटिंग", "nav.notifications": "सूचनाएँ", "nav.weather": "मौसम",
  "common.save": "सहेजें", "common.cancel": "रद्द करें", "common.add": "जोड़ें", "common.delete": "हटाएँ", "common.edit": "बदलें", "common.search": "खोजें",
  "common.loading": "लोड हो रहा है...", "common.none": "अभी कुछ नहीं है।", "common.back": "वापस", "common.submit": "जमा करें", "common.logout": "साइन आउट", "common.login": "साइन इन",
  "common.register": "खाता बनाएँ", "common.yes": "हाँ", "common.no": "नहीं", "common.language": "भाषा", "common.price": "कीमत", "common.status": "स्थिति",
  "auth.mobile": "मोबाइल नंबर या ईमेल", "auth.password": "पासवर्ड", "auth.forgot": "पासवर्ड भूल गए?", "auth.otp": "कोड से साइन इन करें", "auth.code": "कोड",
  "auth.verify": "सत्यापित करें", "auth.name": "पूरा नाम", "auth.role": "मैं हूँ", "auth.send": "कोड भेजें",
  "home.welcome": "स्वागत है", "home.crops": "चालू फसलें", "home.orders": "चल रहे ऑर्डर", "home.wallet": "वॉलेट", "home.alerts": "अनपढ़ी सूचनाएँ",
  "home.advice": "आपके लिए सलाह", "home.harvest": "जल्द कटाई", "home.appointments": "आने वाले परामर्श",
  "farm.add": "खेत जोड़ें", "farm.name": "खेत का नाम", "farm.area": "क्षेत्रफल (एकड़)", "farm.village": "गाँव", "farm.district": "ज़िला", "farm.fields": "प्लॉट",
  "crop.add": "फसल जोड़ें", "crop.sowing": "बुवाई की तारीख", "crop.harvest": "अनुमानित कटाई", "crop.records": "रिकॉर्ड", "crop.profit": "लाभ / हानि",
  "doctor.title": "मेरी फसल जाँचें", "doctor.upload": "प्रभावित पत्ती की साफ़ फोटो लें या चुनें", "doctor.note": "यह केवल मार्गदर्शन है। कुछ भी छिड़कने से पहले विशेषज्ञ से पुष्टि करें।",
  "assistant.ask": "अपनी फसल के बारे में सवाल पूछें", "assistant.speak": "बोलें", "assistant.listen": "सुनें", "assistant.send": "भेजें",
  "shop.add": "कार्ट में डालें", "shop.cart": "कार्ट", "shop.checkout": "ऑर्डर करें", "shop.compare": "तुलना करें", "shop.wish": "बाद के लिए रखें", "shop.cod": "डिलीवरी पर नकद",
  "shop.wallet": "वॉलेट से भुगतान", "shop.address": "डिलीवरी का पता",
  "iot.pump": "पानी का पंप", "iot.on": "चालू करें", "iot.off": "बंद करें", "iot.auto": "स्वचालित", "iot.manual": "हाथ से", "iot.moisture": "मिट्टी की नमी", "iot.open": "मॉनिटरिंग साइट खोलें",
  "wallet.balance": "शेष राशि", "wallet.add": "पैसे जोड़ें", "support.new": "शिकायत दर्ज करें", "settings.privacy": "गोपनीयता", "settings.delete": "खाता हटाने का अनुरोध",
};

const mr: Dict = {
  "nav.home": "मुख्यपृष्ठ", "nav.farms": "माझी शेते", "nav.crops": "पिके", "nav.soil": "माती", "nav.doctor": "पीक डॉक्टर", "nav.assistant": "कृषिमित्रला विचारा",
  "nav.market": "खरेदी", "nav.orders": "ऑर्डर", "nav.machines": "यंत्र भाड्याने", "nav.devices": "उपकरणे", "nav.experts": "तज्ज्ञ", "nav.community": "समुदाय",
  "nav.learn": "शिका", "nav.schemes": "योजना", "nav.wallet": "वॉलेट", "nav.support": "मदत", "nav.settings": "सेटिंग्ज", "nav.notifications": "सूचना", "nav.weather": "हवामान",
  "common.save": "जतन करा", "common.cancel": "रद्द करा", "common.add": "जोडा", "common.delete": "काढून टाका", "common.edit": "बदला", "common.search": "शोधा",
  "common.loading": "लोड होत आहे...", "common.none": "अजून काही नाही.", "common.back": "मागे", "common.submit": "सादर करा", "common.logout": "साइन आउट", "common.login": "साइन इन",
  "common.register": "खाते उघडा", "common.yes": "होय", "common.no": "नाही", "common.language": "भाषा", "common.price": "किंमत", "common.status": "स्थिती",
  "auth.mobile": "मोबाइल नंबर किंवा ईमेल", "auth.password": "पासवर्ड", "auth.forgot": "पासवर्ड विसरलात?", "auth.otp": "कोडने साइन इन करा", "auth.code": "कोड",
  "auth.verify": "पडताळा", "auth.name": "पूर्ण नाव", "auth.role": "मी आहे", "auth.send": "कोड पाठवा",
  "home.welcome": "स्वागत आहे", "home.crops": "चालू पिके", "home.orders": "सुरू असलेले ऑर्डर", "home.wallet": "वॉलेट", "home.alerts": "न वाचलेल्या सूचना",
  "home.advice": "तुमच्यासाठी सल्ला", "home.harvest": "लवकरच काढणी", "home.appointments": "येणारे सल्लामसलत",
  "farm.add": "शेत जोडा", "farm.name": "शेताचे नाव", "farm.area": "क्षेत्र (एकर)", "farm.village": "गाव", "farm.district": "जिल्हा", "farm.fields": "प्लॉट",
  "crop.add": "पीक जोडा", "crop.sowing": "पेरणीची तारीख", "crop.harvest": "अपेक्षित काढणी", "crop.records": "नोंदी", "crop.profit": "नफा / तोटा",
  "doctor.title": "माझे पीक तपासा", "doctor.upload": "बाधित पानाचा स्पष्ट फोटो घ्या किंवा निवडा", "doctor.note": "हे फक्त मार्गदर्शन आहे. काही फवारण्यापूर्वी तज्ज्ञांकडून खात्री करा.",
  "assistant.ask": "तुमच्या पिकाबद्दल प्रश्न विचारा", "assistant.speak": "बोला", "assistant.listen": "ऐका", "assistant.send": "पाठवा",
  "shop.add": "कार्टमध्ये टाका", "shop.cart": "कार्ट", "shop.checkout": "ऑर्डर द्या", "shop.compare": "तुलना करा", "shop.wish": "नंतरसाठी ठेवा", "shop.cod": "डिलिव्हरीवर रोख",
  "shop.wallet": "वॉलेटमधून पैसे द्या", "shop.address": "डिलिव्हरीचा पत्ता",
  "iot.pump": "पाण्याचा पंप", "iot.on": "सुरू करा", "iot.off": "बंद करा", "iot.auto": "स्वयंचलित", "iot.manual": "हाताने", "iot.moisture": "मातीतील ओलावा", "iot.open": "मॉनिटरिंग साइट उघडा",
  "wallet.balance": "शिल्लक", "wallet.add": "पैसे जमा करा", "support.new": "तक्रार नोंदवा", "settings.privacy": "गोपनीयता", "settings.delete": "खाते हटवण्याची विनंती",
};

const DICTS: Record<Lang, Dict> = { en, hi, mr };
export const LANGS: { code: Lang; label: string }[] = [{ code: "en", label: "English" }, { code: "hi", label: "हिन्दी" }, { code: "mr", label: "मराठी" }];
export const SPEECH_LOCALE: Record<Lang, string> = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

let current: Lang = "en";
const listeners = new Set<() => void>();

try { const saved = localStorage.getItem("km_lang"); if (saved === "hi" || saved === "mr" || saved === "en") current = saved; } catch { /* storage may be blocked */ }

export function getLang(): Lang { return current; }
export function setLang(l: Lang): void {
  current = l;
  try { localStorage.setItem("km_lang", l); } catch { /* ignore */ }
  if (typeof document !== "undefined") document.documentElement.lang = l;
  listeners.forEach((f) => f());
}
export function onLang(f: () => void): () => void { listeners.add(f); return () => { listeners.delete(f); }; }
export function t(key: string): string { return DICTS[current][key] ?? en[key] ?? key; }
