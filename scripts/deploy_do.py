"""Create or update the PlainPath app on DigitalOcean App Platform from .do/app.yaml.

SECRET env values are read from the local .env and sent only to the DigitalOcean API (stored encrypted there);
they are never written to the repo. Needs DIGITALOCEAN_TOKEN in .env.

Usage (from repo root):  .venv/Scripts/python scripts/deploy_do.py [--dry-run]
"""
import json
import sys
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.digitalocean.com/v2"


def load_spec(env: dict) -> dict:
    spec = yaml.safe_load((ROOT / ".do" / "app.yaml").read_text(encoding="utf-8"))
    missing = []
    for comp in spec.get("services", []) + spec.get("workers", []):
        filled = []
        for e in comp.get("envs", []):
            e = dict(e)
            e.setdefault("type", "GENERAL")
            if e["type"] == "SECRET":
                value = (env.get(e["key"]) or "").strip()
                if not value:
                    missing.append(f"{comp['name']}.{e['key']}")
                e["value"] = value
            filled.append(e)
        comp["envs"] = filled
    if missing:
        sys.exit(f"Missing values in .env for: {', '.join(missing)}")
    return spec


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    token = (env.get("DIGITALOCEAN_TOKEN") or "").strip()
    if not token:
        sys.exit("DIGITALOCEAN_TOKEN is not set in .env")
    spec = load_spec(env)
    if "--dry-run" in sys.argv:
        redacted = json.loads(json.dumps(spec))
        for comp in redacted.get("services", []) + redacted.get("workers", []):
            for e in comp["envs"]:
                if e["type"] == "SECRET":
                    e["value"] = "<redacted>"
        print(json.dumps(redacted, indent=1)[:3000])
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(base_url=API, headers=headers, timeout=60) as client:
        r = client.post("/apps/propose", json={"spec": spec})
        if r.status_code >= 400:
            sys.exit(f"Spec rejected by DigitalOcean ({r.status_code}): {r.text[:1500]}")
        proposal = r.json()
        print("monthly cost estimate (USD):", proposal.get("app_cost"), "| tier:", proposal.get("app_tier_slug"))

        apps = client.get("/apps", params={"per_page": 100}).json().get("apps", [])
        existing = next((a for a in apps if a["spec"]["name"] == spec["name"]), None)
        if existing:
            r = client.put(f"/apps/{existing['id']}", json={"spec": spec})
        else:
            r = client.post("/apps", json={"spec": spec})
        if r.status_code >= 400:
            sys.exit(f"Deploy failed ({r.status_code}): {r.text[:1500]}")
        app = r.json()["app"]
        print(("updated" if existing else "created"), "app", app["id"])
        print("default ingress:", app.get("default_ingress") or "(assigned after first deploy)")


if __name__ == "__main__":
    main()
