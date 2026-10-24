# PlainPath Navigator

**Government websites, in plain words, in your language.**

PlainPath helps blind and low-vision users, older adults, and people with limited English get things done on
official government websites. Describe what you need in any language; PlainPath answers with simple numbered
steps taken only from the official website, and every step links to the official page with the date it was checked.

## What you can ask

- "I want to renew my disabled parking placard in Contra Costa. I only speak Chinese."
- "What documents do I need for a REAL ID?"
- "I moved. How do I change my address with the DMV?"
- "What is form REG 195 used for?"

Currently covered: California DMV (dmv.ca.gov), crawled with Apify.

## How it works

1. **Navigator** (this agent) understands your request with Bitdeer AI Model Studio: the service, the location,
   the official website, and the language you want.
2. **Answer agent** searches the crawled official pages (MongoDB Atlas Vector Search) and writes short steps at an
   elementary reading level, citing the official source for each step.
3. If nothing relevant is on the official website, PlainPath says so and gives the agency's contact page. It never
   answers from memory.

## Good to know

- Information comes from the official website. Always check the linked original page.
- PlainPath does not give legal or medical advice.

Keywords: government services, DMV, disabled parking placard, REAL ID, change of address, accessibility,
plain language, translation, multilingual, forms, public services
