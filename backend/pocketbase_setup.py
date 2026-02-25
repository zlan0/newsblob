"""
PocketBase Setup Script for GhanaFront v2
Run this ONCE after deploying PocketBase to create the articles collection.

Usage:
  python pocketbase_setup.py --url https://your-pb.fly.dev --email admin@... --password ...
"""
import httpx, argparse, json, sys

def setup(url: str, email: str, password: str):
    print(f"Connecting to PocketBase at {url}...")

    # Auth
    r = httpx.post(f"{url}/api/admins/auth-with-password",
        json={"identity": email, "password": password})
    if r.status_code != 200:
        print(f"❌ Auth failed: {r.text}"); sys.exit(1)
    token = r.json()["token"]
    headers = {"Authorization": token, "Content-Type": "application/json"}
    print("✅ Authenticated")

    # Create articles collection
    schema = {
        "name": "articles",
        "type": "base",
        "schema": [
            {"name":"title",         "type":"text",   "required":True,  "options":{"max":500}},
            {"name":"title_hash",    "type":"text",   "required":True,  "options":{"max":64}},
            {"name":"content",       "type":"text",   "required":False, "options":{"max":20000}},
            {"name":"summary",       "type":"text",   "required":False, "options":{"max":1000}},
            {"name":"url",           "type":"url",    "required":False},
            {"name":"image_url",     "type":"url",    "required":False},
            {"name":"source",        "type":"text",   "required":True,  "options":{"max":100}},
            {"name":"region",        "type":"text",   "required":False, "options":{"max":50}},
            {"name":"category",      "type":"text",   "required":False, "options":{"max":50}},
            {"name":"status",        "type":"select", "required":False,
                "options":{"maxSelect":1,"values":["pending","published","draft","reviewed"]}},
            {"name":"is_original",   "type":"bool",   "required":False},
            {"name":"ai_rewritten",  "type":"bool",   "required":False},
            {"name":"published_at",  "type":"date",   "required":False},
            {"name":"views",         "type":"number", "required":False, "options":{"min":0}},
            {"name":"shares",        "type":"number", "required":False, "options":{"min":0}},
            {"name":"trending_score","type":"number", "required":False},
        ],
        "listRule": None,    # Public read
        "viewRule": None,
        "createRule": "@request.auth.id != ''",
        "updateRule": "@request.auth.id != ''",
        "deleteRule": "@request.auth.id != ''",
    }

    r = httpx.post(f"{url}/api/collections", json=schema, headers=headers)
    if r.status_code in (200, 400):
        if "already exists" in r.text:
            print("ℹ️  Articles collection already exists")
        else:
            print(f"✅ Articles collection created")
    else:
        print(f"⚠️  Collection creation: {r.status_code} {r.text[:200]}")

    print("\n✅ PocketBase setup complete!")
    print(f"   Admin UI: {url}/_/")
    print(f"   API: {url}/api/collections/articles/records")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="PocketBase URL")
    p.add_argument("--email", required=True, help="Admin email")
    p.add_argument("--password", required=True, help="Admin password")
    args = p.parse_args()
    setup(args.url, args.email, args.password)
