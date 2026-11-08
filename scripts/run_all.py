#!/usr/bin/env python3
"""Runs the WHOLE project on your machine and produces every real artefact (results/, report, reflection, zip).

    python3 scripts/run_all.py              # run all stages, resuming from where it stopped
    python3 scripts/run_all.py --status     # show which stages are done
    python3 scripts/run_all.py --from train # restart from a stage (also: --only STAGE, --reset)

Stages: preflight cluster ollama label clean train release evaluate deploy evidence ci finalize
Needs Linux or WSL2 (bash, GNU date), Docker, k3d, kubectl, git, Ollama running with
`OLLAMA_HOST=0.0.0.0 ollama serve`, and ideally the GitHub CLI `gh` (logged in) for the release and CI runs.
Nothing is simulated: every number comes from running the real tools; a failing stage stops the run with the reason.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

REPO = "amitishusharma2005-prog/cs3081-kd-command-parser"
REPO_URL = f"https://github.com/{REPO}"
STATE = ".pipeline_state.json"
LOG = "results/pipeline_run.log"
LOGGING = True
PY = sys.executable
S3_LOCAL = "http://localhost:8333"
STAGES = ["preflight", "cluster", "ollama", "label", "clean", "train", "release", "evaluate", "deploy", "evidence", "ci", "finalize"]


class StageError(Exception):
    pass


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOGGING:
        os.makedirs("results", exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run(cmd, check=True, env=None, tee=None, quiet=False):
    shell = isinstance(cmd, str)
    if not quiet:
        log(f"$ {cmd if shell else ' '.join(cmd)}")
    p = subprocess.Popen(cmd, shell=shell, executable="/bin/bash" if shell else None, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, **(env or {})})
    out = []
    for line in p.stdout:
        if not quiet:
            sys.stdout.write(line)
        out.append(line)
    rc = p.wait()
    text = "".join(out)
    if tee:
        os.makedirs(os.path.dirname(tee) or ".", exist_ok=True)
        with open(tee, "w", encoding="utf-8") as f:
            f.write(f"# {datetime.utcnow().isoformat()}Z  $ {cmd if shell else ' '.join(cmd)}  (exit {rc})\n{text}")
    if check and rc != 0:
        raise StageError(f"command failed (exit {rc}): {cmd if shell else ' '.join(cmd)}\n{text[-1500:]}")
    return rc, text


def retry(fn, tries=3, wait=10, what=""):
    for i in range(1, tries + 1):
        try:
            return fn()
        except StageError as e:
            if i == tries:
                raise
            log(f"RETRY {i}/{tries} {what}: {str(e).splitlines()[0]}")
            time.sleep(wait)


def load_creds():
    with open(".secrets/s3.env") as f:
        for ln in f:
            if "=" in ln:
                k, v = ln.strip().split("=", 1)
                os.environ[k] = v


@contextlib.contextmanager
def port_forward(address="127.0.0.1"):
    p = subprocess.Popen(["kubectl", "-n", "data", "port-forward", "--address", address, "svc/seaweedfs-s3", "8333:8333"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", 8333), 1).close()
                break
            except OSError:
                time.sleep(1)
        else:
            raise StageError("could not port-forward svc/seaweedfs-s3")
        yield
    finally:
        p.terminate()
        with contextlib.suppress(Exception):
            p.wait(10)


def s3():
    import boto3
    from botocore.config import Config
    load_creds()
    return boto3.client("s3", endpoint_url=S3_LOCAL, region_name="us-east-1",
                        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))


def gh_ok():
    return shutil.which("gh") is not None and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0


def ask(prompt):
    if not sys.stdin.isatty():
        raise StageError("manual step needed but no terminal available: " + prompt)
    return input(prompt + " ")


# ---------------------------------------------------------------- stages
def preflight():
    missing = [t for t in ("docker", "k3d", "kubectl", "git", "bash") if not shutil.which(t)]
    if missing:
        raise StageError(f"missing tools: {missing}. Install them (Linux/WSL2) and re-run.")
    run(["docker", "info"], quiet=True)
    need = {"torch": "training/requirements.txt", "transformers": "training/requirements.txt", "boto3": "training/requirements.txt",
            "yaml": "training/requirements.txt", "pytest": "requirements-dev.txt", "locust": "requirements-dev.txt",
            "reportlab": None, "pypdf": None, "fastapi": "requirements-dev.txt", "ruff": "requirements-dev.txt"}
    miss = [m for m in need if subprocess.run([PY, "-c", f"import {m}"], capture_output=True).returncode != 0]
    if miss:
        log(f"installing Python packages for: {miss}")
        run([PY, "-m", "pip", "install", "-r", "training/requirements.txt", "-r", "requirements-dev.txt", "reportlab", "pypdf"])
    run([PY, "-m", "ruff", "check", "."], tee="results/lint.log")
    run([PY, "-m", "pytest", "-v", "tests"], tee="results/pytest_output.log")
    run([PY, "tools/nacl_sim.py", "network/nacl.json", "network/packets_sample.jsonl", "--check"], tee="results/nacl_check.log")
    run(["git", "--version"], quiet=True)


def cluster():
    run("k3d cluster list cs3081-cluster >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml")
    run("bash scripts/secrets.sh")
    run("kubectl apply -f cluster/seaweedfs.yaml")
    run("kubectl -n data rollout status deploy/seaweedfs --timeout=300s")
    run("kubectl -n data wait --for=condition=complete job/seed-buckets --timeout=300s")
    run("kubectl get nodes,ns && kubectl -n data get all,pvc", tee="results/cluster_state_data.log")


DEFAULT_OLLAMA_URL = "http://host.k3d.internal:11434"
OLLAMA_URL_FILE = "results/ollama_url.txt"
OLLAMA_DIAG = "results/ollama_diag.log"
CLUSTER = "cs3081-cluster"


def sh(cmd, timeout=120):
    """Quiet shell helper: returns (exit code, stdout+stderr). Never raises."""
    try:
        p = subprocess.run(cmd, shell=True, executable="/bin/bash", capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {cmd}"


def diag(msg):
    log(msg)
    os.makedirs("results", exist_ok=True)
    with open(OLLAMA_DIAG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def ollama_local_ok():
    try:
        tags = json.load(urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5))
        return any(m["name"].startswith("phi3.5") for m in tags.get("models", []))
    except (OSError, ValueError):
        return False


def ollama_listens_on_all():
    """True/False if we can tell which address Ollama is bound to; None if unknown."""
    rc, out = sh("ss -ltnH 2>/dev/null")
    rows = [ln.split() for ln in out.splitlines() if ":11434" in ln]
    addrs = [r[3] for r in rows if len(r) >= 4 and r[3].endswith(":11434")]
    if not addrs:
        return None
    diag(f"Ollama is listening on: {addrs}")
    return any(a.startswith(("0.0.0.0:", "*:", "[::]:")) for a in addrs)


def restart_ollama_on_all_interfaces():
    diag("restarting Ollama bound to 0.0.0.0 (a loopback-only Ollama cannot be reached from pods)")
    sh("sudo -n systemctl disable --now ollama 2>/dev/null; sudo -n pkill -x ollama 2>/dev/null; pkill -x ollama 2>/dev/null; true", timeout=60)
    time.sleep(3)
    os.makedirs("results", exist_ok=True)
    subprocess.Popen("OLLAMA_HOST=0.0.0.0 OLLAMA_NUM_PARALLEL=2 nohup ollama serve >> results/ollama_server.log 2>&1 &",
                     shell=True, executable="/bin/bash", start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if ollama_local_ok():
            return
        time.sleep(1)
    raise StageError("Ollama did not come back after restart; see results/ollama_server.log")


def wait_cluster_ready():
    """After a Windows/WSL restart the k3d containers need a moment: start them and wait for the node."""
    sh(f"k3d cluster start {CLUSTER}", timeout=180)
    rc, out = sh("kubectl wait --for=condition=Ready node --all --timeout=240s", timeout=260)
    if rc != 0:
        raise StageError("Kubernetes node is not Ready yet:\n" + out[-800:] + "\nWait a minute and run again.")
    sh("kubectl create namespace pipeline --dry-run=client -o yaml | kubectl apply -f -")


def candidate_bases():
    """Every address a pod might use to reach the host (WSL/Ubuntu) where Ollama runs."""
    ips = re.compile(r"\d+\.\d+\.\d+\.\d+")
    hosts = ["host.k3d.internal"]
    rc, out = sh(f"docker network inspect k3d-{CLUSTER} -f '{{{{range .IPAM.Config}}}}{{{{.Gateway}}}} {{{{end}}}}'")
    hosts += [g for g in out.split() if ips.fullmatch(g)]
    rc, out = sh("hostname -I")
    hosts += [g for g in out.split() if ips.fullmatch(g) and not g.startswith("127.")]
    hosts.append("host.docker.internal")
    seen, res = set(), []
    for h in hosts:
        if h not in seen:
            seen.add(h)
            res.append(f"http://{h}:11434")
    return res[:8]


def pod_probe(base):
    """Run curl INSIDE a pod against base/api/tags (the same view the workers will have). Returns (ok, details)."""
    name = "ollama-check"
    sh(f"kubectl -n pipeline delete pod {name} --ignore-not-found --now", timeout=90)
    rc, out = sh(f"kubectl -n pipeline run {name} --restart=Never --image=curlimages/curl:8.10.1 "
                 f"--command -- curl -sS -m 15 {base}/api/tags")
    if rc != 0:
        return False, "could not create probe pod: " + out.strip()[-300:]
    phase, waiting = "", ""
    for _ in range(90):  # up to 3 min (first run may pull the image)
        time.sleep(2)
        phase = sh(f"kubectl -n pipeline get pod {name} -o jsonpath='{{.status.phase}}'")[1].strip()
        waiting = sh(f"kubectl -n pipeline get pod {name} -o jsonpath='{{.status.containerStatuses[0].state.waiting.reason}}'")[1].strip()
        if phase in ("Succeeded", "Failed"):
            break
    logs = sh(f"kubectl -n pipeline logs {name}")[1].strip()
    sh(f"kubectl -n pipeline delete pod {name} --ignore-not-found --now", timeout=90)
    return ("phi3.5" in logs), f"phase={phase} {waiting} | {logs[:300]}"


def open_host_firewall():
    """Last resort when pods time out: allow port 11434 into the Ubuntu VM (harmless on a laptop VM)."""
    rc, out = sh("sudo -n iptables -I INPUT 1 -p tcp --dport 11434 -j ACCEPT")
    diag(f"firewall rule for 11434: exit {rc} {out.strip()[:120]}")


def ollama():
    if not ollama_local_ok():
        if shutil.which("ollama") is None:
            raise StageError("ollama is not installed in Ubuntu: run setup_and_run.sh / the .bat again")
        restart_ollama_on_all_interfaces()
        if not any(m["name"].startswith("phi3.5") for m in json.load(urllib.request.urlopen("http://localhost:11434/api/tags", timeout=10)).get("models", [])):
            run(["ollama", "pull", "phi3.5"])
    if ollama_listens_on_all() is False:  # up, but only on 127.0.0.1: pods can never reach it
        restart_ollama_on_all_interfaces()
    wait_cluster_ready()
    open(OLLAMA_DIAG, "w").write(f"# Ollama reachability from pods, {datetime.now().isoformat(timespec='seconds')}\n")
    for round_no in (1, 2):
        for base in candidate_bases():
            ok, why = pod_probe(base)
            diag(f"{'OK  ' if ok else 'FAIL'} {base}  {why}")
            if ok:
                with open(OLLAMA_URL_FILE, "w") as f:
                    f.write(base + "\n")
                log(f"pods reach Ollama at {base}; the workers will use this address")
                return
        if round_no == 1:
            open_host_firewall()
    raise StageError("no pod could reach Ollama on this machine. Details are in results/ollama_diag.log "
                     "(look at the curl error: 'Could not resolve host' = DNS, 'Connection refused' = Ollama bound to 127.0.0.1, "
                     "'timed out' = firewall). Send me the last 30 lines of that file.")


def worker_manifest():
    """cluster/pipeline-workers.yaml with the Ollama address that the ollama stage found to work from inside pods."""
    url = DEFAULT_OLLAMA_URL
    if os.path.exists(OLLAMA_URL_FILE):
        url = open(OLLAMA_URL_FILE).read().strip() or DEFAULT_OLLAMA_URL
    txt = open("cluster/pipeline-workers.yaml", encoding="utf-8").read().replace(DEFAULT_OLLAMA_URL, url)
    path = "results/pipeline-workers.applied.yaml"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Generated from cluster/pipeline-workers.yaml: OLLAMA_URL = {url}\n" + txt)
    return path


def label():
    wait_cluster_ready()  # after a dropped WSL session the cluster containers may need a moment / a start
    run(["docker", "build", "-f", "worker/Dockerfile", "-t", "teacher-worker:local", "."])
    # a dropped session can leave a half-finished import helper container behind, which blocks the next import
    retry(lambda: run(f"docker rm -f k3d-{CLUSTER}-tools >/dev/null 2>&1; k3d image import teacher-worker:local -c {CLUSTER}"),
          tries=3, wait=15, what="k3d image import")
    run(f"kubectl apply -f {worker_manifest()}")
    log("workers started (labelling 3,000 commands on CPU can take hours; safe to Ctrl-C and re-run: workers checkpoint)")
    while True:
        jobs = json.loads(run("kubectl -n pipeline get jobs -o json", quiet=True)[1])["items"]
        def _state(j):
            conds = {c["type"]: c["status"] for c in j["status"].get("conditions", [])}
            if j["status"].get("succeeded") or conds.get("Complete") == "True":
                return "done"
            if conds.get("Failed") == "True" or j["status"].get("failed", 0) > 3:
                return "failed"
            return "running"
        st = {j["metadata"]["name"]: _state(j) for j in jobs}
        prog = {n: run(f"kubectl -n pipeline logs job/{n} --tail=1", check=False, quiet=True)[1].strip() for n in st}
        log(f"workers: {st} | {prog}")
        if "failed" in st.values():
            raise StageError("a worker job failed; see: kubectl -n pipeline logs job/worker-0")
        if st and all(v == "done" for v in st.values()):
            break
        time.sleep(60)
    run("kubectl -n pipeline get jobs,pods -o wide", tee="results/pipeline_jobs.log")
    run("kubectl -n pipeline get jobs -o custom-columns=NAME:.metadata.name,START:.status.startTime,END:.status.completionTime >> results/pipeline_jobs.log")
    for n in ("worker-0", "worker-1"):
        run(f"kubectl -n pipeline logs job/{n}", tee=f"results/{n}.log")
    os.makedirs("datasets/teacher", exist_ok=True)
    with port_forward():
        c = s3()
        lines = []
        for b in ("datasets", "models"):
            for o in c.list_objects_v2(Bucket=b).get("Contents", []):
                lines.append(f"s3://{b}/{o['Key']}  {o['Size']} bytes")
        with open("results/buckets.log", "w") as f:
            f.write("# buckets: " + ", ".join(x["Name"] for x in c.list_buckets()["Buckets"]) + "\n" + "\n".join(lines) + "\n")
        for k in (0, 1):
            c.download_file("datasets", f"teacher/shard-{k}.jsonl", f"datasets/teacher/shard-{k}.jsonl")
    n = [sum(1 for _ in open(f"datasets/teacher/shard-{k}.jsonl")) for k in (0, 1)]
    log(f"shard sizes: {n}")


def clean():
    rc, o1 = run([PY, "worker/clean.py"], tee="results/clean_run1.log")
    h1 = open("datasets/v1/train.sha256").read()
    run([PY, "worker/clean.py"], tee="results/clean_run2.log", quiet=True)
    h2 = open("datasets/v1/train.sha256").read()
    with open("results/clean_determinism.log", "w") as f:
        f.write(f"run1 {h1}run2 {h2}identical={h1 == h2}\n")
    if h1 != h2:
        raise StageError("clean.py is not deterministic")
    run([PY, "scripts/check_submission.py"], check=False, tee="results/check_after_clean.log", quiet=True)
    c = json.load(open("datasets/v1/clean_report.json"))
    if c["kept"] < 1500:
        log(f"WARNING only {c['kept']} cleaned records (< 1500): training will use all of them")


def train():
    load_creds()
    env = {"S3_ENDPOINT": S3_LOCAL}
    with port_forward():
        run(f"{PY} training/train.py --subset 50", tee="results/train_subset50.log")
        for v in ("v1", "v2"):
            run(f"{PY} training/train.py --version {v}", env=env, tee=f"results/train_{v}.log")
            info = json.load(open(f"models/{v}/version.json"))
            if info["smoke_fallback"]:
                raise StageError("Hugging Face hub unreachable: a random smoke model was trained. Fix the network and re-run --from train.")
        c = s3()
        with open("results/models_bucket.log", "w") as f:
            for o in c.list_objects_v2(Bucket="models").get("Contents", []):
                f.write(f"s3://models/{o['Key']}  {o['Size']} bytes\n")
    for v in ("v1", "v2"):
        shutil.copy(f"training/loss_{v}.csv", f"results/loss_{v}.csv")


def git_commit(msg):
    if not os.path.isdir(".git"):
        run("git init -b main")
    run('git config user.name "Amit Sharma" && git config user.email "amitishusharma2005@gmail.com"', quiet=True)
    if subprocess.run(["git", "remote"], capture_output=True, text=True).stdout.strip() == "":
        run(f"git remote add origin {REPO_URL}.git")
    run("git add -A")
    run(["git", "commit", "-m", msg], check=False)


def git_push():
    rc, _ = run("git push -u origin main", check=False)
    if rc != 0:
        log("WARNING git push was rejected (the remote may already have other commits). Reconcile manually, e.g. "
            "'git pull --rebase origin main', then re-run this stage. I never force-push branches.")
        return False
    rc, _ = run("git tag -f final && git push -f origin final", check=False)  # only the tag is moved
    return rc == 0


def release():
    git_commit("Teacher data, trained student metadata and checksums")
    run("git tag -f final")
    pushed = git_push()
    assets = ["dist/model-v1.tar.gz", "dist/model-v2.tar.gz"]
    if pushed and gh_ok():
        if run(f"gh release view final -R {REPO}", check=False, quiet=True)[0] == 0:
            run(f"gh release upload final {' '.join(assets)} --clobber -R {REPO}")
        else:
            run(f"gh release create final {' '.join(assets)} -R {REPO} --title 'Model assets' "
                "--notes 'Pythia-70M students (v1, v2): model + tokenizer + version.json. Checksums in models/*/model.sha256.'")
    else:
        ask(f"Push the repo and upload {assets} as assets of GitHub release tag 'final' at {REPO_URL}/releases, then press Enter:")
    lines = []
    for v in ("v1", "v2"):
        want = open(f"models/{v}/model.sha256").read().split()[0]
        data = urllib.request.urlopen(f"{REPO_URL}/releases/download/final/model-{v}.tar.gz", timeout=600).read()
        got = hashlib.sha256(data).hexdigest()
        lines.append(f"{'MATCH' if got == want else 'MISMATCH'} {v} release={got} file={want}")
    with open("results/release_checksum.log", "w") as f:
        f.write("\n".join(lines) + "\n")
    log("; ".join(lines))
    if any(x.startswith("MISMATCH") for x in lines):
        raise StageError("release asset checksum differs from models/*/model.sha256")


def evaluate():
    run(f"{PY} training/evaluate.py --mode teacher --name teacher")
    run(f"{PY} training/evaluate.py --mode untrained --name untrained")
    run(f"{PY} training/evaluate.py --mode student --model-dir models/v1 --name student_v1")
    run(f"{PY} training/evaluate.py --mode student --model-dir models/v2 --name student_v2")
    shutil.copy("results/student_v1_predictions.jsonl", "results/predictions.jsonl")
    for n in ("teacher", "untrained", "student_v1", "student_v2"):
        r = json.load(open(f"results/{n}_validation.json"))
        log(f"{n}: validity {r['json_validity']}  full_frame {r['full_frame']}")
    s = json.load(open("results/student_v1_validation.json"))
    t = json.load(open("results/teacher_validation.json"))
    if s["json_validity"] < 95:
        log("WARNING student v1 JSON validity < 95%: the hidden-test requirement (>= 95%) is at risk")
    if s["full_frame"] < t["full_frame"] / 2:
        log("WARNING student full_frame is below half of the teacher's")


def curl(args, tee_append):
    rc, out = run(f"curl -si -m 60 {args}", check=False, quiet=True)
    with open(tee_append, "a") as f:
        f.write(out + "\n")
    return out


def deploy():
    run("make up")
    sz = json.loads(run("docker image inspect command-parser:local", quiet=True)[1])[0]["Size"]
    with open("results/image_size.txt", "w") as f:
        f.write(f"{sz / 1e6:.1f}\n")
    log(f"image size {sz / 1e6:.1f} MB")
    run("kubectl get ns,deploy,svc,ingress,hpa,pods -A -o wide", tee="results/cluster_state_app.log")
    run("kubectl -n app get deploy command-parser -o yaml", tee="results/deployment_applied.yaml")
    smoke = "results/smoke_parse.log"
    open(smoke, "w").write("# POST /parse through the Ingress (localhost:8080)\n")
    for t in ("what is the weather in london", "set an alarm for seven thirty am tomorrow", "what time is it in tokyo"):
        curl(f"-X POST http://localhost:8080/parse -H 'content-type: application/json' -d '{{\"text\":\"{t}\"}}'", smoke)
    run("kubectl -n app set env deploy/command-parser FAULT_INJECT=1 && kubectl -n app rollout status deploy/command-parser --timeout=600s")
    open("results/fault_inject.log", "w").write("# FAULT_INJECT=1\n")
    curl("-X POST http://localhost:8080/parse -H 'content-type: application/json' -d '{\"text\":\"what is the weather in london\"}'", "results/fault_inject.log")
    run("kubectl -n app set env deploy/command-parser FAULT_INJECT=0 && kubectl -n app rollout status deploy/command-parser --timeout=600s")


def evidence():
    load_creds()
    with port_forward("0.0.0.0"):
        run("bash scripts/evidence.sh docker50")
    for step in ("readiness", "coldstart", "top", "hpa", "rollout", "recovery"):
        run(f"bash scripts/evidence.sh {step}", check=False)
    run([PY, "scripts/cost.py"], tee="results/cost_run.log")
    run([PY, "scripts/summarize.py"], quiet=True)
    log("evidence collected; open results/summary.json to see parsed values")


def gh_run(candidate):
    def latest():
        rows = json.loads(run(f"gh run list -R {REPO} --workflow ci.yml --limit 10 --json databaseId,status,url,event", quiet=True)[1])
        return [r for r in rows if r["event"] == "workflow_dispatch"]
    before = max([r["databaseId"] for r in latest()], default=0)
    run(f"gh workflow run ci.yml -R {REPO} -f candidate={candidate}")
    for _ in range(180):
        time.sleep(20)
        new = [r for r in latest() if r["databaseId"] > before]
        if new and new[0]["status"] == "completed":
            jobs = json.loads(run(f"gh run view {new[0]['databaseId']} -R {REPO} --json jobs", quiet=True)[1])["jobs"]
            return new[0]["url"], {j["name"]: j["conclusion"] for j in jobs}
    raise StageError("CI run did not finish in time")


def ci():
    git_commit("Evidence from deployment tests")
    git_push()
    if gh_ok():
        url, jobs = gh_run("untrained")
        log(f"untrained run {url}: {jobs}")
        if jobs.get("quality-gate") != "failure":
            raise StageError(f"expected the quality gate to FAIL for the untrained model, got {jobs}")
        open("results/failed_gate_run_url.txt", "w").write(url + "\n")
        url2, jobs2 = gh_run("student")
        log(f"student run {url2}: {jobs2}")
        open("results/passing_run_url.txt", "w").write(url2 + "\n")
        open("results/ci_jobs.json", "w").write(json.dumps({"untrained": jobs, "student": jobs2}, indent=2))
    else:
        log("gh CLI not available/logged in: run the workflow manually (Actions -> ci -> Run workflow)")
        for name, cand in (("failed_gate", "untrained"), ("passing", "student")):
            u = ask(f"Paste the URL of the finished '{cand}' run ({'must fail at quality-gate' if cand == 'untrained' else 'must pass'}):").strip()
            if not re.match(rf"https://github.com/{REPO}/actions/runs/\d+$", u):
                raise StageError("not a run URL of this repository")
            open(f"results/{name}_run_url.txt", "w").write(u + "\n")


def build_docs():
    run([PY, "scripts/summarize.py"], quiet=True)
    run([PY, "scripts/build_report.py"])
    run([PY, "scripts/build_reflection.py"])


def finalize():
    global LOGGING
    build_docs()
    git_commit("Report, reflection and results")
    gl = "docker run --rm -v \"$PWD\":/repo zricethezav/gitleaks:v8.21.2 detect --source /repo --no-banner --redact"
    rc, out = run(gl, check=False, tee="results/gitleaks.log")
    with open("results/gitleaks.log", "a") as f:
        f.write(f"exit={rc}\n")
    build_docs()
    git_commit("Final submission")
    run("git tag -f final")
    LOGGING = False  # keep the working tree identical to the final commit from here on
    git_push()
    rc, out = run([PY, "scripts/check_submission.py"], check=False)
    run([PY, "scripts/package_submission.py"])
    print("\nDONE. Submit ONLY ./230103033.zip" + ("" if rc == 0 else "  (some checks FAILED above: fix them, then re-run --only finalize)"))


FUNCS = {n: globals()[n] for n in STAGES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start")
    ap.add_argument("--only")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    state = json.load(open(STATE)) if os.path.exists(STATE) and not a.reset else {}
    if a.status:
        for s in STAGES:
            print(f"{s:10} {state.get(s, 'pending')}")
        return
    todo = [a.only] if a.only else STAGES[STAGES.index(a.start):] if a.start else [s for s in STAGES if state.get(s) != "done"]
    for s in todo:
        log(f"=== STAGE {s} ===")
        t0 = time.time()
        try:
            FUNCS[s]()
        except (StageError, KeyboardInterrupt, OSError) as e:
            log(f"STAGE_FAILED {s}: {e}")
            print(f"\nStage '{s}' stopped. Fix the cause and run again; finished stages are skipped.", file=sys.stderr)
            sys.exit(1)
        state[s] = "done"
        json.dump(state, open(STATE, "w"), indent=1)
        log(f"stage {s} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
