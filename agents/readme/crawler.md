# PlainPath Crawler

Keeps PlainPath's copy of official government websites fresh, using **Apify**:

1. Checks when the site was last crawled (MongoDB Atlas `sites`). Data younger than 24 hours is used as is.
2. Otherwise starts the Apify pipeline: **Website Content Crawler** for every public page (robots.txt respected),
   then the custom **PlainPath Gov Extractor** Actor for steps, required documents, PDF form fields, addresses
   and fees. Results are embedded and stored automatically.
3. Reports crawl progress in the conversation. If Apify fails, it falls back to the cached official data and says
   how old that data is.

Try: "Is the dmv.ca.gov data fresh?" or "refresh dmv.ca.gov".

Part of PlainPath (Navigator, Crawler, Answer, Form agents).
