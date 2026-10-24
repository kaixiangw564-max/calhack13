"use client";

import { FormEvent, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { LANGUAGES, findLanguage, languageLabel } from "./languages";
import { Recognition, canSpeak, getRecognitionCtor, speak, stopSpeaking } from "./speech";

type Cited = { text: string; source_url: string; crawled_at: string };
type Form = { number: string | null; name: string; url: string; source_url: string; crawled_at: string };
type Answer = {
  steps: Cited[];
  documents: Cited[];
  forms: Form[];
  not_found: boolean;
  disclaimer?: string;
  message?: string;
  contact?: { url: string; title: string } | null;
};

const EXAMPLES = [
  "How do I renew my disabled parking placard?",
  "What documents do I need for a REAL ID?",
  "I moved. How do I change my address with the DMV?",
];

// Browser capabilities never change during a visit; read them without effects (server snapshot = unsupported).
const noSubscribe = () => () => {};
function useBrowserValue<T>(getClient: () => T, server: T): T {
  return useSyncExternalStore(noSubscribe, getClient, () => server);
}
function browserLanguage(): string {
  const code = navigator.language?.split("-")[0];
  return LANGUAGES.some((l) => l.code === code) ? code : "en";
}

function formatDate(iso: string, locale: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return d.toLocaleDateString(locale, { year: "numeric", month: "long", day: "numeric" });
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const [langChoice, setLangCode] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const voiceSupported = useBrowserValue(() => getRecognitionCtor() !== null, false);
  const ttsSupported = useBrowserValue(canSpeak, false);
  const defaultLang = useBrowserValue(browserLanguage, "en");
  const recognitionRef = useRef<Recognition | null>(null);
  const wantListeningRef = useRef(false);
  const resultsHeadingRef = useRef<HTMLHeadingElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const langCode = langChoice ?? defaultLang;
  const lang = findLanguage(langCode);

  useEffect(
    () => () => {
      stopSpeaking();
      wantListeningRef.current = false;
      recognitionRef.current?.stop();
    },
    [],
  );

  useEffect(() => {
    if (answer) resultsHeadingRef.current?.focus();
  }, [answer]);

  async function submit(text: string) {
    const q = text.trim();
    if (!q) {
      setError("Please type or say your question first.");
      inputRef.current?.focus();
      return;
    }
    stopSpeaking();
    setSpeaking(null);
    setLoading(true);
    setError("");
    setAnswer(null);
    setStatus("Searching the official website. This can take up to 20 seconds.");
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, language: lang.code }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || data?.detail || "Something went wrong.");
      setAnswer(data as Answer);
      setStatus(
        data.not_found ? "No answer was found on the official website." : `Answer ready with ${data.steps.length} steps.`,
      );
    } catch (e) {
      setStatus("");
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(question);
  }

  // Voice input stops only when the user presses "Stop listening". Browsers still end a recognition
  // session on long silence or network hiccups, so we restart it and keep what was already recognized.
  function toggleListening() {
    if (listening) {
      wantListeningRef.current = false;
      recognitionRef.current?.stop(); // onend submits the transcript
      return;
    }
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    const joiner = ["zh", "ja"].includes(lang.code) ? "" : " ";
    let committed = ""; // final text from earlier (auto-restarted) sessions
    let session = ""; // final text from the current session
    const rec = new Ctor();
    rec.lang = lang.speech;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onresult = (event) => {
      let finals = "";
      let interim = "";
      for (const result of Array.from(event.results)) {
        if (result.isFinal) finals += result[0].transcript + joiner;
        else interim += result[0].transcript;
      }
      session = finals;
      setQuestion((committed + session + interim).trim());
    };
    rec.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        wantListeningRef.current = false;
        setError("Microphone access was blocked. Allow the microphone in your browser, or type your question.");
      } else if (event.error === "audio-capture") {
        wantListeningRef.current = false;
        setError("No microphone was found. Check your microphone, or type your question.");
      }
      // "no-speech", "network", "aborted": onend decides whether to keep listening.
    };
    rec.onend = () => {
      committed += session;
      session = "";
      if (wantListeningRef.current) {
        try {
          rec.start();
          return;
        } catch {
          wantListeningRef.current = false;
        }
      }
      setListening(false);
      recognitionRef.current = null;
      const text = committed.trim();
      if (text) {
        setQuestion(text);
        void submit(text);
      } else {
        setStatus("");
        setError((cur) => cur || "Sorry, I could not hear that. Please try again or type your question.");
      }
    };
    recognitionRef.current = rec;
    wantListeningRef.current = true;
    setQuestion("");
    setError("");
    setStatus("Listening. Speak your question, then press Stop listening.");
    setListening(true);
    rec.start();
  }

  function toggleSpeak(id: string, text: string) {
    if (speaking === id) {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    setSpeaking(id);
    speak(text, lang.speech, () => setSpeaking((cur) => (cur === id ? null : cur)));
  }

  const allStepsText = answer?.steps.map((s, i) => `${i + 1}. ${s.text}`).join(" ") ?? "";

  return (
    <>
      <form onSubmit={onSubmit} className="flex flex-col gap-4" aria-describedby="ask-help">
        <label htmlFor="question" className="text-2xl font-bold">
          What do you need to do?
        </label>
        <p id="ask-help" className="text-muted">
          Ask in any language. Type your question, or press &quot;Speak your question&quot;, talk, then press &quot;Stop
          listening&quot; when you are done.
        </p>
        <textarea
          id="question"
          ref={inputRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit(question);
            }
          }}
          rows={3}
          className="w-full rounded-lg border-2 border-line bg-paper p-4 text-xl text-ink"
          placeholder="Example: How do I renew my disabled parking placard?"
          aria-invalid={error && !question.trim() ? true : undefined}
        />

        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label htmlFor="language" className="font-bold">
              Answer language
            </label>
            <select
              id="language"
              value={langCode}
              onChange={(e) => setLangCode(e.target.value)}
              className="min-h-12 rounded-lg border-2 border-line bg-paper px-3 text-lg text-ink"
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code} suppressHydrationWarning>
                  {languageLabel(l.code)}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={toggleListening}
            disabled={!voiceSupported || loading}
            aria-pressed={listening}
            aria-describedby={voiceSupported ? undefined : "voice-unsupported"}
            className="min-h-12 rounded-lg border-2 border-primary bg-paper px-5 text-lg font-bold text-primary hover:bg-panel disabled:border-line disabled:text-muted"
          >
            <span aria-hidden="true">{listening ? "\u25A0 " : "\u{1F3A4} "}</span>
            {listening ? "Stop listening" : "Speak your question"}
          </button>

          <button
            type="submit"
            disabled={loading}
            className="min-h-12 rounded-lg bg-primary px-6 text-lg font-bold text-white hover:bg-primary-hover disabled:opacity-70"
          >
            {loading ? "Searching..." : "Get the steps"}
          </button>
        </div>
        {!voiceSupported && (
          <p id="voice-unsupported" className="text-muted">
            Voice input is not available in this browser. You can still type your question.
          </p>
        )}
      </form>

      <section aria-labelledby="examples-heading" className="mt-6">
        <h2 id="examples-heading" className="text-lg font-bold">
          Try an example
        </h2>
        <ul className="mt-2 flex flex-wrap gap-3">
          {EXAMPLES.map((ex) => (
            <li key={ex}>
              <button
                type="button"
                onClick={() => {
                  setQuestion(ex);
                  void submit(ex);
                }}
                className="min-h-12 rounded-lg border-2 border-line bg-panel px-4 text-left text-base text-ink hover:border-primary"
              >
                {ex}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <p role="status" aria-live="polite" className="mt-6 min-h-8 text-lg font-bold">
        {status}
      </p>
      {error && (
        <p role="alert" className="rounded-lg border-2 border-danger bg-paper p-4 text-lg font-bold text-danger">
          {error}
        </p>
      )}

      {answer && (
        <section
          aria-labelledby="results-heading"
          className="mt-4 flex flex-col gap-8"
          lang={lang.speech}
          dir={lang.rtl ? "rtl" : "ltr"}
        >
          <h2 id="results-heading" ref={resultsHeadingRef} tabIndex={-1} className="text-3xl font-bold" lang="en" dir="ltr">
            {answer.not_found ? "Not found on the official website" : "Your steps"}
          </h2>

          {answer.not_found ? (
            <div className="rounded-lg bg-panel p-6 text-2xl">
              <p>{answer.message}</p>
              {answer.contact && (
                <p className="mt-4">
                  <a href={answer.contact.url} target="_blank" rel="noopener noreferrer" lang="en" dir="ltr">
                    Contact the agency: {answer.contact.title}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                </p>
              )}
            </div>
          ) : (
            <>
              {ttsSupported && (
                <div lang="en" dir="ltr">
                  <button
                    type="button"
                    onClick={() => toggleSpeak("all", allStepsText)}
                    aria-pressed={speaking === "all"}
                    className="min-h-12 rounded-lg bg-primary px-5 text-lg font-bold text-white hover:bg-primary-hover"
                  >
                    {speaking === "all" ? "Stop reading" : "Read all steps aloud"}
                  </button>
                </div>
              )}

              <ol className="flex flex-col gap-6">
                {answer.steps.map((step, i) => (
                  <li key={i} className="rounded-lg border-2 border-line bg-paper p-5">
                    <p className="text-2xl leading-relaxed">
                      <span className="font-bold">{i + 1}. </span>
                      {step.text}
                    </p>
                    <div className="mt-4 flex flex-wrap items-center gap-4 text-lg" lang="en" dir="ltr">
                      <a href={step.source_url} target="_blank" rel="noopener noreferrer" className="font-bold">
                        View original<span className="sr-only"> official page for step {i + 1} (opens in a new tab)</span>
                      </a>
                      {ttsSupported && (
                        <button
                          type="button"
                          onClick={() => toggleSpeak(`step-${i}`, step.text)}
                          aria-pressed={speaking === `step-${i}`}
                          className="min-h-11 rounded-lg border-2 border-primary px-4 font-bold text-primary hover:bg-panel"
                        >
                          {speaking === `step-${i}` ? "Stop" : "Read aloud"}
                          <span className="sr-only"> step {i + 1}</span>
                        </button>
                      )}
                      <span className="text-muted">
                        Checked on <time dateTime={step.crawled_at}>{formatDate(step.crawled_at, lang.speech)}</time>
                      </span>
                    </div>
                  </li>
                ))}
              </ol>

              {answer.documents.length > 0 && (
                <section aria-labelledby="docs-heading">
                  <h3 id="docs-heading" className="text-2xl font-bold" lang="en" dir="ltr">
                    What to bring
                  </h3>
                  <ul className="mt-3 flex list-disc flex-col gap-3 ps-8 text-xl">
                    {answer.documents.map((d, i) => (
                      <li key={i}>
                        {d.text}{" "}
                        <a href={d.source_url} target="_blank" rel="noopener noreferrer" className="text-lg" lang="en">
                          View original<span className="sr-only"> page for document {i + 1} (opens in a new tab)</span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {answer.forms.length > 0 && (
                <section aria-labelledby="forms-heading" lang="en" dir="ltr">
                  <h3 id="forms-heading" className="text-2xl font-bold">
                    Official forms
                  </h3>
                  <ul className="mt-3 flex flex-col gap-3 text-xl">
                    {answer.forms.map((f) => (
                      <li key={f.url} className="rounded-lg bg-panel p-4">
                        <a href={f.url} target="_blank" rel="noopener noreferrer" className="font-bold">
                          {f.number ? `${f.number}: ` : ""}
                          {f.name}
                          <span className="sr-only"> (official form, opens in a new tab)</span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}

          {answer.disclaimer && (
            <p className="border-t-2 border-line pt-4 text-lg text-muted">{answer.disclaimer}</p>
          )}
        </section>
      )}
    </>
  );
}
