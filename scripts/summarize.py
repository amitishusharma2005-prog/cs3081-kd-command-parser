"""Turn the raw logs in results/ into results/summary.json. Only parses what the tools really wrote;
anything that is missing or unparsable stays None (never guessed).   python scripts/summarize.py"""
import csv
import json
import os
import re
import statistics


def read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None


def jload(p):
    t = read(p)
    return json.loads(t) if t else None


def agg(path):
    try:
        with open(path, newline="") as f:
            r = next(x for x in csv.DictReader(f) if x["Name"] == "Aggregated")
    except (FileNotFoundError, StopIteration):
        return None
    n, fl = int(r["Request Count"]), int(r["Failure Count"])
    return {"requests": n, "failures": fl, "failure_percent": round(100 * fl / n, 3) if n else None,
            "p50_ms": float(r["50%"]), "p95_ms": float(r["95%"]), "rps": float(r["Requests/s"])}


def coldstart(text):
    runs = {}
    for m in re.finditer(r"run (\d+) \S+ created=\S+ ready=\S+ seconds=(-?\d+)", text or ""):
        runs.setdefault(int(m.group(1)), []).append(int(m.group(2)))
    if not runs:
        return None
    per_run = {k: max(v) for k, v in sorted(runs.items())}  # time until every new Pod is Ready
    return {"per_run_seconds": per_run, "median_seconds": statistics.median(per_run.values()),
            "definition": "per run = slowest new Pod, creationTimestamp -> Ready; median over runs"}


def docker50(text):
    if not text:
        return None
    ok = re.search(r"ok=(\d+)/50", text)
    peak = re.search(r"peak memory \(cgroup\): (\d+)", text)
    oom = re.search(r"OOMKilled: (\w+)", text)
    mems = re.findall(r"mem ([\d.]+)(MiB|GiB)", text)
    seen = max((float(v) * (1024 if u == "GiB" else 1) for v, u in mems), default=None)
    return {"ok": int(ok.group(1)) if ok else None, "oom_killed": oom.group(1) if oom else None,
            "peak_mib_cgroup": round(int(peak.group(1)) / 2**20, 1) if peak else None,
            "peak_mib_docker_stats": round(seen, 1) if seen else None}


def hpa(text):
    rep = [int(m.group(3)) for m in re.finditer(r"command-parser-hpa\s+\S+\s+.*?\s(\d+)\s+(\d+)\s+(\d+)\s+\S+\s*$", text or "", re.M)]
    if not rep:
        return None
    first2 = next((i for i, v in enumerate(rep) if v >= 2), None)
    return {"observations": len(rep), "start_replicas": rep[0], "max_replicas_seen": max(rep), "final_replicas": rep[-1],
            "scaled_up_1_to_2": rep[0] == 1 and first2 is not None,
            "scaled_back_to_1": first2 is not None and 1 in rep[first2:]}


def recovery(text):
    if not text:
        return None
    last = text.rsplit("--- ", 1)[-1]
    return {"running_ready_pods_at_end": len(re.findall(r"command-parser-\S+\s+1/1\s+Running", last))}


def readiness(text):
    if not text:
        return None
    ep = re.findall(r"command-parser-svc\s+(\S+)", text)
    return {"samples": len(ep), "saw_no_endpoints": any(e == "<none>" for e in ep),
            "later_had_endpoints": any(e != "<none>" for e in ep[ep.index("<none>") + 1:]) if "<none>" in ep else False}


def top(text):
    return [{"pod": m.group(1), "cpu": m.group(2), "memory": m.group(3)}
            for m in re.finditer(r"^(command-parser-\S+)\s+(\d+m)\s+(\d+Mi)", text or "", re.M)] or None


def main():
    hdr = jload("results/loadtest_headers.json")
    shares = None
    if hdr:
        tot = sum(hdr["per_replica"].values())
        shares = {k: round(100 * v / tot, 2) for k, v in hdr["per_replica"].items()} if tot else None
    gl = read("results/gitleaks.log")
    rb = read("results/rolling_update_rollback.log") or ""
    final_ver = re.findall(r"x-model-version:\s*(\S+)", rb, re.I)
    img = read("results/image_size.txt")
    S = {
        "clean": jload("datasets/v1/clean_report.json"),
        "scores": {n: jload(f"results/{n}_validation.json") for n in ("teacher", "untrained", "student_v1", "student_v2")},
        "loadtest": agg("results/loadtest_stats.csv"), "headers": hdr, "replica_share_percent": shares,
        "rollout": agg("results/rollout_stats.csv"), "rollout_versions_seen": (jload("results/rollout_headers.json") or {}).get("per_model_version"),
        "version_after_rollback": final_ver[-1] if final_ver else None, "recovery_load": agg("results/recovery_stats.csv"),
        "recovery_pods": recovery(read("results/pod_recovery.log")), "readiness": readiness(read("results/readiness_gate.log")),
        "hpa": hpa(read("results/hpa_scaling.log")), "coldstart": coldstart(read("results/cold_start_times.log")),
        "docker50": docker50(read("results/docker_50req_limit_test.log")), "top": top(read("results/kubectl_top_pods.log")),
        "cost": jload("results/cost_slo.json"), "image_size_mb": float(img) if img else None,
        "gitleaks_clean": (("no leaks found" in gl.lower()) and "exit=0" in gl) if gl else None,
        "failed_gate_run_url": (read("results/failed_gate_run_url.txt") or "").strip() or None,
        "passing_run_url": (read("results/passing_run_url.txt") or "").strip() or None,
        "release_checksum_ok": ("MATCH v1" in (read("results/release_checksum.log") or "")) and ("MATCH v2" in (read("results/release_checksum.log") or "")) or None,
        "unit_tests": (re.search(r"(\d+) passed", read("results/pytest_output.log") or "") or [None, None])[1],
    }
    os.makedirs("results", exist_ok=True)
    with open("results/summary.json", "w") as f:
        json.dump(S, f, indent=2)
    print(json.dumps(S, indent=2))
    return S


if __name__ == "__main__":
    main()
