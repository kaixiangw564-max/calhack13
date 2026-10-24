# PlainPath

**Government websites, in plain words, in your language.**

PlainPath helps blind and low-vision users, older adults, and people with limited English use public-service websites. Say what you need in any language (e.g. *"I want to renew my disabled parking placard, I only speak Chinese"*). PlainPath finds the answer in an **official website crawled with Apify** (including PDF forms) and returns simple numbered steps, required documents, and form explanations. **Every step links to the official source page and shows when it was crawled.**

Two entry points share one backend and one set of agents:

1. **ASI:One chat**: the full flow runs inside ASI:One through four Fetch.ai uAgents (Navigator, Crawler, Answer, Form) that use the Agent Chat Protocol and Interactive Cards.
2. **Accessible website**: large type, high contrast, keyboard-only operation, screen-reader friendly, voice input and read-aloud.

> Information comes from official websites. Always check the linked original. PlainPath does not give legal or medical advice.

## Architecture

_TODO (step 11)_

## Running locally

_TODO: filled in as each build step lands (see PROGRESS.md)._

## How each prize requirement is met

_TODO (step 11): one row per requirement._

### How we use Bitdeer AI Model Studio

_TODO_

### How we use Apify

_TODO_

## Repository layout

```
actor/     Custom Apify Actor "PlainPath Gov Extractor"
backend/   FastAPI + shared core logic (LLM, embeddings, retrieval, ingest, crawl, forms)
agents/    Four uAgents (Navigator, Crawler, Answer, Form) using the Agent Chat Protocol
web/       Next.js accessible website
```
