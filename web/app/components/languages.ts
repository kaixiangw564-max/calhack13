// Languages offered in the picker. Native names are produced at runtime with Intl.DisplayNames,
// so this source file stays ASCII-only. `speech` is the BCP 47 tag used for voice input/output.
export type Language = { code: string; speech: string; rtl?: boolean };

export const LANGUAGES: Language[] = [
  { code: "en", speech: "en-US" },
  { code: "zh", speech: "zh-CN" },
  { code: "es", speech: "es-US" },
  { code: "vi", speech: "vi-VN" },
  { code: "ko", speech: "ko-KR" },
  { code: "tl", speech: "fil-PH" },
  { code: "ru", speech: "ru-RU" },
  { code: "hy", speech: "hy-AM" },
  { code: "fa", speech: "fa-IR", rtl: true },
  { code: "ar", speech: "ar-SA", rtl: true },
  { code: "hi", speech: "hi-IN" },
  { code: "pa", speech: "pa-IN" },
  { code: "ja", speech: "ja-JP" },
  { code: "km", speech: "km-KH" },
];

export function languageLabel(code: string): string {
  try {
    const native = new Intl.DisplayNames([code], { type: "language" }).of(code) ?? code;
    const english = new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
    return native === english ? english : `${native} (${english})`;
  } catch {
    return code;
  }
}

export function findLanguage(code: string): Language {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
}
