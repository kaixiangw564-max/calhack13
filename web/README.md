# PlainPath web

Accessible Next.js (App Router) front end: one question box, voice input, large high-contrast answers, and a
"View original" link plus "Read aloud" button on every step.

```bash
cd web
npm install
BACKEND_URL=http://localhost:8000 npm run dev   # FastAPI backend from ../backend
```

- The browser only calls `/api/ask` (a Route Handler) on this origin, which forwards to `BACKEND_URL` server-side.
- Voice input and read-aloud use the browser Web Speech API; when unavailable the page works with typing only.
- Accessibility: skip link, labeled controls, `aria-live` status, focus moves to the results heading, 4px focus
  ring, WCAG AA contrast (see `app/globals.css`), and `lang`/`dir` set on answers for screen-reader pronunciation.
