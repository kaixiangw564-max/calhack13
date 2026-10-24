import AskPanel from "./components/AskPanel";

export default function Home() {
  return (
    <>
      <header className="border-b-2 border-line bg-panel">
        <div className="mx-auto max-w-4xl px-5 py-5">
          <p className="text-3xl font-bold text-primary">PlainPath</p>
          <p className="text-lg text-muted">Government websites, in plain words, in your language.</p>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-4xl flex-1 px-5 py-8">
        <h1 className="sr-only">Ask PlainPath a question about a government service</h1>
        <AskPanel />
      </main>

      <footer className="border-t-2 border-line bg-panel">
        <div className="mx-auto max-w-4xl px-5 py-5 text-base text-muted">
          <p>
            Answers come only from official government websites crawled with Apify. Every step links to the original
            page. PlainPath does not give legal or medical advice.
          </p>
        </div>
      </footer>
    </>
  );
}
