"""Task 7 cost + SLO from the real Locust output and data/rate_card.json.

python scripts/cost.py [--replicas 2] [--cpu-limit 1] [--mem-limit-gib 1] [--slo 99]
"""
import argparse
import csv
import json

ap = argparse.ArgumentParser()
ap.add_argument("--stats", default="results/loadtest_stats.csv")
ap.add_argument("--rates", default="data/rate_card.json")
ap.add_argument("--replicas", type=int, default=2)
ap.add_argument("--cpu-limit", type=float, default=1.0)
ap.add_argument("--mem-limit-gib", type=float, default=1.0)
ap.add_argument("--slo", type=float, default=99.0, help="target success percent per load-test run")
ap.add_argument("--out", default="results/cost_slo.json")
a = ap.parse_args()
rates = json.load(open(a.rates))
row = next(r for r in csv.DictReader(open(a.stats)) if r["Name"] == "Aggregated")
total, fails, rps = int(row["Request Count"]), int(row["Failure Count"]), float(row["Requests/s"])
per_replica_hour = a.cpu_limit * rates["vcpu_hour"] + a.mem_limit_gib * rates["gib_memory_hour"]
hourly = a.replicas * per_replica_hour
req_per_hour = rps * 3600
cost = hourly / req_per_hour * 1000
budget = total * (100 - a.slo) / 100
res = {
    "requests": total, "failures": fails, "error_rate_percent": round(100 * fails / total, 4),
    "p50_ms": float(row["50%"]), "p95_ms": float(row["95%"]), "requests_per_second": rps,
    "hourly_cost_per_replica": per_replica_hour, "hourly_cost_all_replicas": hourly,
    "requests_per_hour": req_per_hour, "currency": rates["currency"],
    "cost_per_1000_requests": round(cost, 4),
    "slo": f">= {a.slo}% of requests return HTTP 200 within 30 s over one 2-minute load-test run",
    "error_budget_requests": round(budget, 2), "budget_used_requests": fails,
    "budget_used_percent": round(100 * fails / budget, 2) if budget else None,
}
json.dump(res, open(a.out, "w"), indent=2)
print(json.dumps(res, indent=2))
