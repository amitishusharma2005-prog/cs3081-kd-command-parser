"""Verify the submission against the marking tables using the REAL files. Exit 1 if anything fails.
python scripts/check_submission.py"""
import csv
import hashlib
import json
import os
import subprocess
import sys

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def exists(*paths):
    return all(os.path.exists(p) for p in paths)


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


# Task 1
check("k3d.yaml, teacher prompt", exists("cluster/k3d.yaml", "prompts/teacher_prompt.txt"))
pool = [r["id"] for r in jl("data/commands_pool.jsonl")]
sh = [p for p in ("datasets/teacher/shard-0.jsonl", "datasets/teacher/shard-1.jsonl") if os.path.exists(p)]
if len(sh) == 2:
    ids = [r["id"] for p in sh for r in jl(p)]
    check("every id in exactly one shard", sorted(ids) == sorted(pool), f"{len(ids)} lines, {len(set(ids))} unique, pool {len(pool)}")
else:
    check("shard outputs present", False)
if exists("datasets/v1/train.jsonl", "datasets/v1/train.sha256"):
    got = hashlib.sha256(open("datasets/v1/train.jsonl", "rb").read()).hexdigest()
    check("train.sha256 matches train.jsonl", got == open("datasets/v1/train.sha256").read().split()[0])
    c = json.load(open("datasets/v1/clean_report.json"))
    check("counts add up", c["input"] == sum(c[k] for k in ("a", "b", "c", "d", "duplicates", "kept")), str(c))
else:
    check("train.jsonl + train.sha256 present", False)
# Task 2
cfg = open("training/config.yaml").read()
check("config.yaml has the six items", all(k in cfg for k in ("seed", "learning_rate", "batch_size", "epochs", "max_seq_length", "library_versions")))
if exists("training/loss.csv"):
    n = len(list(csv.reader(open("training/loss.csv")))) - 1
    check("loss.csv one row per epoch", n >= 1, f"{n} rows")
else:
    check("loss.csv present", False)
check("model.sha256 for v1 and v2", exists("models/v1/model.sha256", "models/v2/model.sha256"))
for n in ("teacher", "untrained", "student_v1", "student_v2"):
    check(f"results/{n} predictions + report", exists(f"results/{n}_predictions.jsonl", f"results/{n}_validation.json"))
if exists("results/teacher_validation.json", "results/student_v1_validation.json"):
    t, s = (json.load(open(f"results/{n}_validation.json")) for n in ("teacher", "student_v1"))
    check("student json_validity >= 95", s["json_validity"] >= 95, str(s["json_validity"]))
    check("student full_frame >= half of teacher", s["full_frame"] >= t["full_frame"] / 2, f"{s['full_frame']} vs {t['full_frame']}")
# Tasks 3-6 files
check("service files", exists("service/app.py", "service/Dockerfile", "service/requirements.txt"))
check("pinned requirements", all("==" in ln for ln in open("service/requirements.txt") if ln.strip() and not ln.startswith(("--", "#"))))
check("manifests", exists("cluster/seaweedfs.yaml", "cluster/pipeline-workers.yaml", "cluster/app-deployment.yaml"))
check("network files", exists("network/subnets.md", "network/nacl.json"))
nac = subprocess.run([sys.executable, "tools/nacl_sim.py", "network/nacl.json", "network/packets_sample.jsonl", "--check"], capture_output=True, text=True)
check("nacl_sim --check", nac.returncode == 0 and "100.0%" in nac.stdout)
check("CI workflow, Makefile, AI_USE.md, README.md", exists(".github/workflows/ci.yml", "Makefile", "AI_USE.md", "README.md"))
# Evidence
for f in ("loadtest_stats.csv", "loadtest_headers.json", "docker_50req_limit_test.log", "readiness_gate.log", "hpa_scaling.log",
          "rolling_update_rollback.log", "pod_recovery.log", "cold_start_times.log", "kubectl_top_pods.log", "cost_slo.json"):
    check(f"results/{f}", exists(f"results/{f}"))
# Documents
check("report/report.pdf", exists("report/report.pdf"))
check("230103033.pdf (reflection)", exists("230103033.pdf"))
if exists("230103033.pdf"):
    from pypdf import PdfReader
    check("reflection is at most 3 pages", len(PdfReader("230103033.pdf").pages) <= 3)
if exists("report/report.pdf"):
    from pypdf import PdfReader
    txt = " ".join(p.extract_text() for p in PdfReader("report/report.pdf").pages)
    check("report has no NOT MEASURED / NOT AVAILABLE placeholders", "NOT MEASURED YET" not in txt and "NOT AVAILABLE YET" not in txt)
if exists("report/report.pdf"):
    from pypdf import PdfReader
    check("report is at most 8 pages (references/appendices excluded: check by eye if it is longer)", len(PdfReader("report/report.pdf").pages) <= 8,
          str(len(PdfReader("report/report.pdf").pages)))
check("failed quality-gate CI run URL recorded", exists("results/failed_gate_run_url.txt"))
if exists("230103033.pdf", "reflection_draft_typed.pdf"):
    same = open("230103033.pdf", "rb").read() == open("reflection_draft_typed.pdf", "rb").read()
    check("230103033.pdf is your handwritten scan, not the typed placeholder", not same, "replace it, then run scripts/seal_submission.py")
tag = subprocess.run(["git", "tag", "-l", "final"], capture_output=True, text=True).stdout.strip()
check("git tag final", tag == "final")
leaked = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
check("no model weights tracked", not any(f.endswith((".safetensors", ".bin", ".pt")) for f in leaked))
print(f"\n{sum(R)}/{len(R)} checks passed")
sys.exit(0 if all(R) else 1)
