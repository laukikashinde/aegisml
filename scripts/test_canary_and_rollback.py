"""
Tests canary advancement → promotion AND the rollback scenario.
Run after test_e2e.py (needs an active canary).
"""
import urllib.request
import json
import sys
import time

base = "http://localhost:8000"
H = {"Content-Type": "application/json", "X-API-Key": "dev-api-key-change-in-production"}


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(base + path, data=data, headers=H, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        return {}


def get(path):
    req = urllib.request.Request(base + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


print("=" * 55)
print("AegisML Canary & Rollback Test")
print("=" * 55)

# ── Part 1: Advance canary to promotion ───────────────────────────────────
print("\n[Part 1] Advancing healthy canary to 100%...")
models = get("/api/models")
canary_mv = next((m for m in models if m["stage"] == "CANARY"), None)

if not canary_mv:
    print("  No active canary found — run test_e2e.py first")
    sys.exit(0)

print(f"  Active canary: v{canary_mv['version']} (f1={canary_mv['f1_score']:.4f})")

# Advance traffic step by step
for step in range(6):
    result = post(f"/api/models/{canary_mv['id']}/verify-canary")
    status = result.get("status", "?")
    traffic = result.get("current_traffic", result.get("traffic_advanced", {}).get("new_traffic", "?"))
    print(f"  Step {step+1}: status={status}  traffic={traffic}")
    if status == "promoted":
        print("  ✓ Canary promoted to production!")
        break
    elif status == "rolled_back":
        print(f"  ✗ Unexpected rollback: {result.get('reason')}")
        break
    time.sleep(0.5)

# Check models after promotion
models = get("/api/models")
print("\n  Model states after promotion:")
for m in models:
    print(f"    v{m['version']}  stage={m['stage']:<12}  f1={m.get('f1_score')}")

# ── Part 2: Rollback scenario ─────────────────────────────────────────────
print("\n[Part 2] Deployment Failure simulation (rollback scenario)...")
sim = post("/api/incidents/simulate", {
    "simulation_type": "DEPLOYMENT_FAILURE",
    "parameters": {"error_rate": 0.18, "latency_ms": 450}
})
iid = sim.get("incident_id")
dep_id = sim.get("deployment_id")
print(f"  incident_id   : {iid}")
print(f"  deployment_id : {dep_id}")

# Investigate
print("\n  Investigating deployment failure...")
diag = post(f"/api/incidents/{iid}/investigate")
print(f"  recommended_action : {diag.get('recommended_action')}")
print(f"  confidence         : {diag.get('confidence')}")

# Remediate (should auto-rollback)
print("\n  Executing remediation (should trigger rollback)...")
result = post(f"/api/incidents/{iid}/remediate")
print(f"  status : {result.get('status')}")
if result.get("result"):
    r = result["result"]
    print(f"  reason : {r.get('reason')}")
    print(f"  production_restored : {r.get('production_restored')}")

# Check final state
inc = get(f"/api/incidents/{iid}")
print(f"\n  Incident status : {inc['status']}")

models = get("/api/models")
print("\n  Model states after rollback:")
for m in models:
    print(f"    v{m['version']}  stage={m['stage']:<12}  f1={m.get('f1_score')}")

# Dashboard
dash = get("/api/dashboard")
print(f"\n  Dashboard metrics:")
print(f"    production_model_v    : {dash['production_model_version']}")
print(f"    auto_remediation_rate : {dash['auto_remediation_rate']:.0%}")
print(f"    rollback_rate         : {dash['rollback_rate']:.0%}")

print("\n" + "=" * 55)
print("CANARY + ROLLBACK TEST COMPLETE")
print("=" * 55)
