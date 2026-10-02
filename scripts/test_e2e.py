"""End-to-end workflow test — run to verify the full pipeline works."""
import urllib.request
import json
import sys

base = "http://localhost:8000"
H = {"Content-Type": "application/json", "X-API-Key": "dev-api-key-change-in-production"}


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(base + path, data=data, headers=H, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        sys.exit(1)


def get(path):
    req = urllib.request.Request(base + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


print("=" * 55)
print("AegisML End-to-End Workflow Test")
print("=" * 55)

print("\n[1] Simulate DATA_DRIFT...")
sim = post("/api/incidents/simulate", {"simulation_type": "DATA_DRIFT",
                                        "parameters": {"income_multiplier": 1.5}})
iid = sim["incident_id"]
print(f"    incident_id: {iid}")
print(f"    description: {sim.get('description', '')[:80]}")

print("\n[2] Investigate...")
diag = post(f"/api/incidents/{iid}/investigate")
print(f"    recommended_action : {diag['recommended_action']}")
print(f"    confidence         : {diag['confidence']}")
print(f"    risk_level         : {diag['risk_level']}")
print(f"    root_cause         : {diag['root_cause'][:100]}")

print("\n[3] Remediate (training ~30-60s)...")
result = post(f"/api/incidents/{iid}/remediate")
print(f"    status : {result.get('status')}")
if result.get("retrain_result"):
    r = result["retrain_result"]
    print(f"    pipeline_run_id : {r.get('pipeline_run_id')}")
    print(f"    model_version   : {r.get('model_version')}")
    m = r.get("metrics", {})
    print(f"    f1_score        : {m.get('f1_score')}")
    print(f"    avg_latency_ms  : {m.get('avg_latency_ms')}")

print("\n[4] Check Pipeline Runs...")
pipes = get("/api/pipelines")
print(f"    Total runs : {len(pipes)}")
if pipes:
    p = pipes[0]
    print(f"    Latest     : status={p['status']} duration={p.get('duration_seconds')}s")
    print(f"    Stages     : {p.get('stages_completed')}")
    if p.get("error_message"):
        print(f"    Error      : {p['error_message'][:200]}")

print("\n[5] Check Models...")
models = get("/api/models")
print(f"    Total versions : {len(models)}")
for m in models:
    print(f"    v{m['version']}  stage={m['stage']:<12}  f1={m.get('f1_score')}  "
          f"latency={m.get('avg_latency_ms')}ms  gates={m.get('quality_gate_passed')}")

print("\n[6] Check Incident Status...")
inc = get(f"/api/incidents/{iid}")
print(f"    status          : {inc['status']}")
print(f"    timeline events : {len(inc['timeline'])}")
print(f"    Recent events:")
for e in inc["timeline"][-5:]:
    print(f"      {e['event_type'][:40]:<42} {e['description'][:60]}")

print("\n[7] Check Dashboard...")
dash = get("/api/dashboard")
print(f"    active_incidents       : {dash['active_incidents']}")
print(f"    production_model_v     : {dash['production_model_version']}")
print(f"    auto_remediation_rate  : {dash['auto_remediation_rate']:.0%}")
print(f"    remediation_success    : {dash['remediation_success_rate']:.0%}")

print("\n" + "=" * 55)
print("WORKFLOW TEST COMPLETE")
print("=" * 55)
