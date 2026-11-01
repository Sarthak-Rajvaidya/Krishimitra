// Voice input and read-aloud use the browser's built-in Web Speech API (no keys, nothing sent to us).
// Support differs by browser and language; the UI hides the buttons when unsupported.
import { getLang, SPEECH_LOCALE } from "./i18n";

type Rec = { lang: string; interimResults: boolean; onresult: (e: any) => void; onerror: () => void; onend: () => void; start: () => void };

export const canListen = () => typeof window !== "undefined" && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export function listen(onText: (s: string) => void, onEnd: () => void): void {
  const C = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  const r: Rec = new C();
  r.lang = SPEECH_LOCALE[getLang()]; r.interimResults = false;
  r.onresult = (e) => onText(e.results[0][0].transcript);
  r.onerror = onEnd; r.onend = onEnd;
  r.start();
}

export function speak(text: string): void {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LOCALE[getLang()];
  window.speechSynthesis.speak(u);
}
