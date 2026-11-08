"""Build report/report.pdf (+ report/report.tex source) from the REAL files in the repo.

Every measured number is read from results/, datasets/, training/, models/. A value whose source file
does not exist yet is printed as 'NOT MEASURED YET (<file>)', so a draft can never contain invented
figures. Run again after each stage of the pipeline.   python scripts/build_report.py
"""
import csv
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

REPO = "https://github.com/amitishusharma2005-prog/cs3081-kd-command-parser"
MISSING = []


def jload(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        MISSING.append(path)
        return None


def first_line(path):
    try:
        with open(path) as f:
            return f.read().split()[0]
    except FileNotFoundError:
        MISSING.append(path)
        return None


def val(v, src, fmt="{}"):
    return fmt.format(v) if v is not None else f"NOT MEASURED YET ({src})"


def stats_row():
    p = "results/loadtest_stats.csv"
    try:
        with open(p) as f:
            return next(r for r in csv.DictReader(f) if r["Name"] == "Aggregated")
    except (FileNotFoundError, StopIteration):
        MISSING.append(p)
        return None


SM = jload("results/summary.json") or {}
CFG = __import__("yaml").safe_load(open("training/config.yaml"))


def sv(*keys, fmt="{}", src="results/summary.json"):
    cur = SM
    for k in keys:
        cur = cur.get(k) if isinstance(cur, dict) else None
    return fmt.format(cur) if cur is not None else f"NOT MEASURED YET ({src}: {'.'.join(keys)})"


ss = getSampleStyleSheet()
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.6, leading=10.6, spaceAfter=3)
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=12, spaceBefore=6, spaceAfter=3)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=9.6, spaceBefore=3, spaceAfter=2)
C = ParagraphStyle("c", parent=B, fontSize=7.4, leading=8.8, spaceAfter=0)


def P(t, s=B):
    return Paragraph(t, s)


def table(rows, widths=None):
    data = [[Paragraph(str(c), C) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


def build():
    counts = jload("datasets/v1/clean_report.json")
    train_sha = first_line("datasets/v1/train.sha256")
    v1sha, v2sha = first_line("models/v1/model.sha256"), first_line("models/v2/model.sha256")
    scores = {n: jload(f"results/{n}_validation.json") for n in ("teacher", "untrained", "student_v1", "student_v2")}
    hdr = jload("results/loadtest_headers.json")
    cost = jload("results/cost_slo.json")
    st = stats_row()
    loss = []
    try:
        with open("training/loss.csv") as f:
            loss = list(csv.reader(f))
    except FileNotFoundError:
        MISSING.append("training/loss.csv")
    S = []
    S += [P("<b>Cloud Computing (CS3081) Mini Project Report</b>", ParagraphStyle("t", parent=H1, fontSize=15)),
          P(f"Amit Sharma (Roll No: 230103033) &nbsp;|&nbsp; Repository: {REPO}")]
    # ---- 1
    S += [P("1. Object storage and parallel teacher labelling (Task 1)", H1),
          P("<b>Architecture.</b> A k3d cluster (<i>cs3081-cluster</i>, config <i>cluster/k3d.yaml</i>, host port 8080 mapped to the load balancer) runs SeaweedFS in namespace <i>data</i> "
            "(S3 gateway on 8333, S3 identities from a generated Secret). A Job creates buckets <i>datasets</i> and <i>models</i> and uploads <i>commands_pool.jsonl</i>. "
            "The teacher is phi3.5 served by Ollama on the laptop (temperature 0, seed 42); pods reach it at <i>" + (open("results/ollama_url.txt").read().strip() if os.path.exists("results/ollama_url.txt") else "http://host.k3d.internal:11434") + "</i> (verified from inside a pod). "
            "<b>Prompt design</b> (<i>prompts/teacher_prompt.txt</i>): states the four keys and eight intents, the three slot rules, and nine few-shot examples taken from the assignment text; "
            "it demands a bare JSON object. <b>Sharding.</b> Two Jobs <i>worker-0/1</i> in namespace <i>pipeline</i> set SHARD_COUNT=2; worker k takes every line i (0-based) with i mod 2 = k. "
            "Each line has exactly one remainder, so every id lands in exactly one shard: no gaps, no repeats. Workers checkpoint to <i>datasets/teacher/shard-k.jsonl</i> and resume after a restart."),
          P("<b>Cleaning</b> (<i>worker/clean.py</i>): records sorted by id, then each gets one verdict: (a) invalid JSON / not an object, (b) wrong keys, (c) invalid intent, (d) slot not null and not a substring of the command, "
            "then duplicate command text (smallest id kept). Output is deterministic, so re-running yields the same checksum.")]
    if counts:
        S += [table([["Input", "(a)", "(b)", "(c)", "(d)", "Duplicates", "Kept"],
                     [counts["input"], counts["a"], counts["b"], counts["c"], counts["d"], counts["duplicates"], counts["kept"]]]),
              P(f"input = a+b+c+d+duplicates+kept: {counts['input']} = {counts['a'] + counts['b'] + counts['c'] + counts['d'] + counts['duplicates'] + counts['kept']}. train.sha256 = <font size=7>{train_sha}</font>")]
    else:
        S += [P("<b>NOT MEASURED YET</b> (datasets/v1/clean_report.json): run the teacher workers and <i>make clean-data</i>.")]
    # ---- 2
    S += [P("2. Training the student (Task 2)", H1),
          P(f"<b>Setup.</b> <i>training/config.yaml</i> holds seed {CFG['seed']}, learning rate {CFG['learning_rate']}, batch size {CFG['batch_size']}, {CFG['epochs']} epochs, max length {CFG['max_seq_length']} and library versions; v2 uses seed {CFG['variants']['v2']['seed']} and {CFG['variants']['v2']['epochs']} epochs. "
            "Examples are <i>Command: &lt;text&gt;\\nJSON: &lt;teacher JSON&gt;</i>. Tokens up to and including 'JSON:' are labelled -100, so cross-entropy covers only the JSON reply and the EOS token. "
            "Seeds are fixed for random, numpy, torch and transformers; AdamW with linear warm-up/decay, gradient clipping at 1.0, first 1,500 cleaned records. Model + tokenizer go to <i>s3://models/v1/</i> and a deterministic tar.gz is the GitHub Release asset."),
          P(f"model.sha256 v1 = <font size=7>{val(v1sha, 'models/v1/model.sha256')}</font>; v2 = <font size=7>{val(v2sha, 'models/v2/model.sha256')}</font>")]
    S += [table([list(r) for r in loss]) if loss else P("<b>NOT MEASURED YET</b> (training/loss.csv)")]
    rows = [["Metric (%)", "Teacher phi3.5", "Untrained Pythia-70M", "Student v1", "Student v2"]]
    for m in ("json_validity", "intent_accuracy", "date_accuracy", "time_accuracy", "place_accuracy", "full_frame"):
        rows.append([m] + [val(scores[n][m] if scores[n] else None, f"results/{n}_validation.json") for n in ("teacher", "untrained", "student_v1", "student_v2")])
    S += [table(rows), P("<b>Discussion.</b> Write after the numbers exist: compare students with the untrained base and with the teacher, and say whether full_frame is at least half of the teacher's.")]
    S += [P("Sequence-level vs logit-based distillation", H2),
          P("(a) <b>Sequence-level KD</b> trains the student with ordinary cross-entropy on the teacher's generated output sequences (hard targets) as if they were labels. "
            "(b) <b>Logit-based KD</b> trains the student to match the teacher's per-token output probability distribution (e.g. KL divergence over the vocabulary), giving soft targets that carry the teacher's uncertainty. "
            "(c) It is impossible here because Phi-3.5 and Pythia-70M use different tokenizers and vocabularies, so their distributions cannot be aligned token by token, and Ollama's API returns only generated text, not full logits. "
            "(d) <b>Limitation:</b> the student only sees one sampled answer per command, so it inherits every teacher mistake that survives cleaning (a wrong but substring-valid slot passes rule (d)) and gets no signal about the teacher's confidence.")]
    # ---- 3
    S += [P("3. Inference service in a container (Task 3)", H1),
          P("<i>service/app.py</i> (FastAPI, port 8000) serves POST /parse, GET /healthz (200 while the process lives) and GET /readyz (503 until the model is loaded, then 200). "
            "Configuration comes only from MODEL_URI, MODEL_VERSION, S3_ENDPOINT, MAX_NEW_TOKENS (plus FAULT_INJECT). At start-up a background thread downloads the model/tokenizer from object storage using credentials from a Kubernetes Secret, "
            "so the process is live but not ready while loading. Every output is validated against <i>data/schema.json</i> (JSON object, exactly four keys, valid intent, slots null or string); failures return HTTP 500 "
            "<i>{\"error\": \"invalid_model_output\"}</i>. FAULT_INJECT=1 replaces the output with <i>not json</i> before validation. Success returns only the four keys plus X-Model-Version and X-Served-By (pod name). "
            "The image uses python:3.11-slim, CPU-only torch wheels and pinned direct dependencies, and contains no weights."),
          P("<b>Measured:</b> image size " + sv("image_size_mb", fmt="{} MB (limit 2048 MB)") + "; 50 sequential requests at --cpus=1.0 --memory=1g: "
            + sv("docker50", "ok", fmt="{}/50 returned HTTP 200") + ", OOMKilled=" + sv("docker50", "oom_killed") + ", peak memory "
            + sv("docker50", "peak_mib_cgroup", fmt="{} MiB (cgroup memory.peak)") + " / " + sv("docker50", "peak_mib_docker_stats", fmt="{} MiB highest docker stats sample") + ". Evidence: results/docker_50req_limit_test.log.")]
    # ---- 4
    S += [P("4. Kubernetes deployment, scaling and reliability (Task 4)", H1),
          P("<i>cluster/app-deployment.yaml</i> (namespace <i>app</i>): Deployment with 2 replicas, RollingUpdate maxUnavailable 0 / maxSurge 1, requests 250m/512Mi, limits 1 CPU/1Gi, liveness on /healthz, readiness on /readyz, "
            "S3 credentials via secretKeyRef; Service on 8000; Traefik Ingress sending /parse to the Service; HPA min 1, max 2, CPU target 70%. "
            "Because readiness depends on /readyz, a Pod receives no traffic (is absent from the Service endpoints) until the model is loaded."),
          P("<b>Limitation of the local cluster:</b> the cluster is a single k3d node on one laptop, so it demonstrates scheduling, self-healing and rolling updates, "
            "but <b>not</b> fault tolerance across machines: if the laptop or Docker daemon fails, every replica fails together. Metrics-server on k3s also reacts slowly, so HPA scale-up/down is delayed."),
          P("<b>Measured</b> (logs in results/, produced by scripts/evidence.sh): readiness gate: Service endpoints showed &lt;none&gt; while the model loaded = " + sv("readiness", "saw_no_endpoints")
            + ", endpoints appeared afterwards = " + sv("readiness", "later_had_endpoints") + ". HPA: scaled 1&rarr;2 = " + sv("hpa", "scaled_up_1_to_2") + ", back to 1 = " + sv("hpa", "scaled_back_to_1")
            + ". Rolling update v1&rarr;v2 under load: " + sv("rollout", "failure_percent", fmt="{}% failed") + " of " + sv("rollout", "requests") + " requests (limit 0.5%); versions served " + sv("rollout_versions_seen")
            + "; after <i>kubectl rollout undo</i> X-Model-Version = " + sv("version_after_rollback") + ". Pod deletion under load: " + sv("recovery_load", "failure_percent", fmt="{}% failed")
            + " (limit 2%), Ready Pods at end = " + sv("recovery_pods", "running_ready_pods_at_end") + ". Cold start per run (s): " + sv("coldstart", "per_run_seconds")
            + ", <b>median " + sv("coldstart", "median_seconds", fmt="{} s") + "</b> (" + (SM.get("coldstart") or {}).get("definition", "definition in scripts/summarize.py") + "); the logs show the S3 download lines."),
          P("<b>Assumptions:</b> the Ingress is reached through k3d's port 8080; HPA reacts at metrics-server's resolution; replicas run on the same node.")]
    if hdr:
        S += [P(f"<b>Measured</b> load balancing (two Ready replicas, standard Locust run): per-replica successful requests {json.dumps(hdr['per_replica'])} = {json.dumps(SM.get('replica_share_percent'))} % (each must be at least 30%); model versions: {json.dumps(hdr['per_model_version'])}.")]
    # ---- 5
    S += [P("5. Subnetting and network access control (Task 5)", H1),
          table([["Subnet", "Needed", "Network", "Prefix", "Usable range", "Broadcast", "Usable"],
                 ["app", 1000, "10.20.0.0", "/22", "10.20.0.1 - 10.20.3.254", "10.20.3.255", 1022],
                 ["public", 250, "10.20.4.0", "/24", "10.20.4.1 - 10.20.4.254", "10.20.4.255", 254],
                 ["data", 100, "10.20.5.0", "/25", "10.20.5.1 - 10.20.5.126", "10.20.5.127", 126],
                 ["management", 20, "10.20.5.128", "/27", "10.20.5.129 - 10.20.5.158", "10.20.5.159", 30]]),
          P("Working: smallest prefix with 2^(32-p) - 2 &gt;= hosts: 1000 &rarr; /22 (1022; /23 gives 510); 250 &rarr; /24 (254); 100 &rarr; /25 (126); 20 &rarr; /27 (30). Blocks placed back to back from 10.20.0.0."),
          table([["Dir", "Rule", "Action", "Protocol/ports", "CIDR"],
                 ["in", 100, "deny", "all", "198.51.100.0/24"], ["in", 110, "allow", "tcp 80", "0.0.0.0/0"], ["in", 120, "allow", "tcp 443", "0.0.0.0/0"],
                 ["in", 130, "allow", "tcp 22", "10.20.5.128/27 (management)"], ["in", 140, "allow", "tcp 1024-65535 (replies)", "10.20.0.0/22 (app)"],
                 ["in", 32000, "deny", "all", "0.0.0.0/0"], ["out", 100, "allow", "tcp 8000", "10.20.0.0/22 (app)"],
                 ["out", 110, "allow", "tcp 1024-65535 (replies)", "0.0.0.0/0"], ["out", 32000, "deny", "all", "0.0.0.0/0"]]),
          P("<b>Measured:</b> <i>nacl_sim.py --check</i> on the sample packets, output in results/nacl_check.log; tests/test_all.py adds 15 further packets."),
          P("A NACL is <b>stateless</b>: it keeps no connection table, so an allowed request does not make its reply allowed. Replies go to the client's ephemeral port (1024-65535), "
            "so each direction needs its own explicit reply rule. Rules are checked lowest number first and the first match wins, so the deny for 198.51.100.0/24 must be numbered below the allows for TCP 80/443; "
            "otherwise a packet from that range to port 443 would match the allow first.")]
    # ---- 6
    S += [P("6. Reproducibility, testing and CI/CD (Task 6)", H1),
          P("<i>make up</i> builds and deploys everything from a fresh clone (cluster, generated secrets, SeaweedFS, models fetched from the GitHub Release and checksum-verified, image, manifests); <i>make down</i> deletes the cluster; "
            "<i>make train [SUBSET=50] [VERSION=v2]</i> trains; <i>make test</i> runs 30 unit tests plus the NACL check. The GitHub Actions workflow runs: lint (ruff) &rarr; unit tests &rarr; model evaluation "
            "(Release asset, checksum verified, score.py on validation.jsonl) &rarr; quality gate (score.py --min-validity 95) &rarr; gitleaks. A manual run with candidate=untrained shows the gate failing."),
          P("<b>Measured:</b> unit tests passed = " + sv("unit_tests") + "; release asset checksums match models/v*/model.sha256 = " + sv("release_checksum_ok")
            + "; gitleaks reported no leaks = " + sv("gitleaks_clean") + ". Failing quality-gate run (untrained Pythia-70M): " + sv("failed_gate_run_url")
            + ". Passing run (student from the Release): " + sv("passing_run_url") + ". AI_USE.md documents the AI tooling and verification.")]
    # ---- 7
    S += [P("7. Performance, cost and review (Task 7)", H1)]
    if st:
        S += [table([["Requests", "Failures", "Error rate", "p50 (ms)", "p95 (ms)", "Req/s"],
                     [st["Request Count"], st["Failure Count"], f"{100 * int(st['Failure Count']) / max(int(st['Request Count']), 1):.2f}%", st["50%"], st["95%"], st["Requests/s"]]])]
    else:
        S += [P("<b>NOT MEASURED YET</b> (results/loadtest_stats.csv): run the standard Locust command against the deployment.")]
    top = "results/kubectl_top_pods.log"
    tp = SM.get("top")
    S += [table([["Pod", "CPU (kubectl top, during load)", "Memory"]] + [[t["pod"], t["cpu"], t["memory"]] for t in tp]) if tp else P("Per-pod CPU/memory: <b>NOT MEASURED YET</b> (results/kubectl_top_pods.log)."),
          P("Cold start: see Section 4. <b>Assumptions:</b> the rate card is hypothetical; replicas are billed for CPU/memory <i>limits</i> for the whole hour; throughput measured over one 2-minute run is assumed to hold for an hour.")]
    if cost:
        S += [P(f"<b>Cost</b> (rate card: {cost['currency']} 3.50 per vCPU-hour, 0.45 per GiB-hour): per replica = 1 x 3.50 + 1 x 0.45 = {cost['hourly_cost_per_replica']:.2f}; all running replicas = "
                f"{cost['hourly_cost_all_replicas']:.2f} per hour; requests per hour = {cost['requests_per_second']} x 3600 = {cost['requests_per_hour']:.0f}; "
                f"cost per 1,000 requests = hourly / requests per hour x 1000 = <b>{cost['cost_per_1000_requests']} {cost['currency']}</b> (estimate, no real charge)."),
              P(f"<b>SLO:</b> {cost['slo']}. Error budget = {cost['requests']} x 1% = {cost['error_budget_requests']} requests; used {cost['budget_used_requests']} ({cost['budget_used_percent']}%).")]
    else:
        S += [P("<b>Cost and SLO: NOT MEASURED YET</b> (results/cost_slo.json from <i>python scripts/cost.py</i>).")]
    ev = lambda v, src, f="{}": val(v, src, f)  # noqa: E731
    S += [table([["Component", "Evidence (measured number)", "Limitation", "Improvement"],
                 ["Data and storage", ev(counts and counts["kept"], "clean_report.json", "{} clean records kept"), "Single SeaweedFS pod, no replication; teacher errors that pass the substring check stay in the data", "Replicated volumes; second-pass validation of teacher labels"],
                 ["Model quality", ev(scores["student_v1"] and scores["student_v1"]["full_frame"], "student_v1_validation.json", "full_frame {}%"), "Sequence-level KD copies teacher mistakes; 70M model", "Larger student or more/cleaner data"],
                 ["Latency and throughput", ev(st and st["95%"], "loadtest_stats.csv", "p95 {} ms"), "One torch thread per replica; no batching", "Dynamic batching, ONNX/quantisation"],
                 ["Resource utilisation", ev(os.path.exists(top) or None, top, "see kubectl top log"), "Requests/limits chosen by estimate", "Tune from measured usage"],
                 ["Reliability and recovery", ev(os.path.exists("results/pod_recovery.log") or None, "pod_recovery.log", "see recovery log"), "Single node: no machine-level fault tolerance", "Multi-node cluster, PodDisruptionBudget"],
                 ["Security and cost", ev(cost and cost["cost_per_1000_requests"], "cost_slo.json", "{} per 1,000 requests"), "Static generated S3 keys, no TLS, replicas billed even when idle", "Short-lived credentials, TLS ingress, scale to demand"]],
                [3 * cm, 4.2 * cm, 5.2 * cm, 4.6 * cm])]
    S += [PageBreak(), P("References", H1),
          P("Kim &amp; Rush (2016) Sequence-Level Knowledge Distillation, EMNLP. Bastianelli et al. (2020) SLURP, EMNLP. Biderman et al. Pythia model card. k3d, SeaweedFS, Kubernetes, Locust, Gitleaks documentation; AWS VPC network ACL guide; Google SRE Book (SLOs).")]
    os.makedirs("report", exist_ok=True)
    doc = SimpleDocTemplate("report/report.pdf", pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm,
                            title="CS3081 Mini Project Report - 230103033", author="Amit Sharma")
    doc.build(S)
    from pypdf import PdfReader
    pages = len(PdfReader("report/report.pdf").pages)
    print(f"report/report.pdf: {pages} pages total (last page is References)")
    if pages - 1 > 8:
        print("WARNING: body exceeds 8 pages")
    if MISSING:
        print("DRAFT: missing measured inputs:\n  " + "\n  ".join(sorted(set(MISSING))))


if __name__ == "__main__":
    build()
