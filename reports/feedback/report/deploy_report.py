"""Create or update the "AI feedback" Power BI report from definition/ (Story 7.4, AD-20).

Uses the Fabric REST API as the Power BI user (powerbi.user@example.com), with a token from a separate az
CLI profile so the owner's normal Azure login is untouched:

    AZURE_CONFIG_DIR=.work/az-powerbi az login --allow-no-subscriptions   # once, as the Power BI user
    python3 reports/feedback/report/deploy_report.py

Looks up the workspace and semantic model by name, binds the report to the model by id, and creates
the report or updates its definition if it already exists.
"""

import argparse
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.fabric.microsoft.com/v1"
HERE = Path(__file__).parent
REPO = HERE.parents[2]


def token(config_dir: str) -> str:
    env = {**os.environ, "AZURE_CONFIG_DIR": config_dir}
    return subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://api.fabric.microsoft.com",
         "--query", "accessToken", "-o", "tsv"],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()


def call(method: str, url: str, tok: str, body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), (json.loads(raw) or {} if raw else {})
    except urllib.error.HTTPError as err:
        raw = err.read()
        raise SystemExit(f"{method} {url} -> {err.code}: {raw.decode(errors='replace')[:2000]}") from None


def wait(status: int, headers: dict, tok: str) -> None:
    """Follow a long-running operation (202 + Location) until it finishes."""
    if status != 202:
        return
    location = headers.get("Location")
    while location:
        time.sleep(int(headers.get("Retry-After", "5")))
        status, headers, body = call("GET", location, tok)
        state = body.get("status")
        if state in ("Succeeded", None) and status == 200:
            return
        if state in ("Failed", "Cancelled"):
            raise SystemExit(f"operation {state}: {json.dumps(body)[:2000]}")


def find(items: list[dict], name: str, what: str) -> dict:
    for item in items:
        if item.get("displayName") == name:
            return item
    names = ", ".join(sorted(i.get("displayName", "?") for i in items))
    raise SystemExit(f"{what} '{name}' not found. Found: {names or 'none'}")


def parts(model_id: str) -> list[dict]:
    def b64(text: str) -> str:
        return base64.b64encode(text.encode()).decode()

    pbir = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={model_id}"}},
    }
    out = [{"path": "definition.pbir", "payload": b64(json.dumps(pbir)), "payloadType": "InlineBase64"}]
    for path in sorted((HERE / "definition").rglob("*.json")):
        rel = "definition/" + path.relative_to(HERE / "definition").as_posix()
        out.append({"path": rel, "payload": b64(path.read_text()), "payloadType": "InlineBase64"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="Formapp")
    parser.add_argument("--model", default="formapp AI feedback")
    parser.add_argument("--report", default="AI feedback")
    parser.add_argument("--config-dir", default=str(REPO / ".work" / "az-powerbi"))
    args = parser.parse_args()

    tok = token(args.config_dir)
    _, _, ws = call("GET", f"{API}/workspaces", tok)
    workspace = find(ws.get("value", []), args.workspace, "Workspace")
    wid = workspace["id"]
    _, _, models = call("GET", f"{API}/workspaces/{wid}/semanticModels", tok)
    model = find(models.get("value", []), args.model, "Semantic model")
    _, _, reports = call("GET", f"{API}/workspaces/{wid}/reports", tok)
    existing = [r for r in reports.get("value", []) if r.get("displayName") == args.report]
    definition = {"parts": parts(model["id"])}

    if existing:
        rid = existing[0]["id"]
        status, headers, _ = call("POST", f"{API}/workspaces/{wid}/reports/{rid}/updateDefinition", tok,
                                  {"definition": definition})
        wait(status, headers, tok)
        print(f"updated report '{args.report}' ({rid}) in '{args.workspace}'")
    else:
        status, headers, body = call("POST", f"{API}/workspaces/{wid}/reports", tok,
                                     {"displayName": args.report, "definition": definition})
        wait(status, headers, tok)
        print(f"created report '{args.report}' in '{args.workspace}' {(body or {}).get('id', '')}")


if __name__ == "__main__":
    main()
