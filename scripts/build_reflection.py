"""Build the written reflection 230103033.pdf (max 3 pages, typed) from the real results.

Numbers come from results/summary.json; 'challenges' come from the pipeline runner's log
(results/pipeline_run.log: failed stages and retries) plus anything you add to my_notes.md.
Print and handwrite/scan it yourself if your instructor needs handwriting.   python scripts/build_reflection.py
"""
import json
import os
import re
import shutil

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

REPO = "https://github.com/amitishusharma2005-prog/cs3081-kd-command-parser"
SM = json.load(open("results/summary.json")) if os.path.exists("results/summary.json") else {}


def g(*keys, fmt="{}", default="not measured"):
    cur = SM
    for k in keys:
        cur = cur.get(k) if isinstance(cur, dict) else None
    return fmt.format(cur) if cur is not None else default


def events():
    p = "results/pipeline_run.log"
    if not os.path.exists(p):
        return []
    return [ln.strip() for ln in open(p, encoding="utf-8", errors="replace") if re.search(r"STAGE_FAILED|RETRY|WARNING", ln)]


def notes():
    return open("my_notes.md", encoding="utf-8").read().strip() if os.path.exists("my_notes.md") else ""


def sections():
    sc = SM.get("scores") or {}
    t, s1 = sc.get("teacher") or {}, sc.get("student_v1") or {}
    ev = events()
    ch = ("The pipeline runner logged these problems while I ran the project: " + " | ".join(ev[:8]) + ".") if ev else \
        "The pipeline runner logged no failed stages or retries in the final run."
    return [
        ("1. What I learned",
         "Sequence-level knowledge distillation trains a small student on the text a larger teacher generates, using ordinary cross-entropy; logit-based distillation would instead match the teacher's "
         "token probability distributions, which was impossible here because Phi-3.5 and Pythia-70M use different vocabularies and Ollama exposes only generated text. "
         "I learned to shard work with a modulo rule (line number mod SHARD_COUNT) so every command lands in exactly one shard, to keep data cleaning deterministic (sorted ids and a SHA-256 of the output), "
         "to separate liveness from readiness so a Pod that is still downloading its model receives no traffic, and that a network ACL is stateless: replies need their own rules and rule numbers decide which match wins."),
        ("2. Challenges and how they were handled", ch + " " + notes()),
        ("3. What I measured",
         f"Cleaning kept {g('clean', 'kept')} of {g('clean', 'input')} teacher replies (rejected a={g('clean', 'a')}, b={g('clean', 'b')}, c={g('clean', 'c')}, d={g('clean', 'd')}, duplicates={g('clean', 'duplicates')}). "
         f"On the 100 validation commands the teacher reached JSON validity {t.get('json_validity', 'n/a')}% and full-frame {t.get('full_frame', 'n/a')}%, the trained student v1 {s1.get('json_validity', 'n/a')}% and {s1.get('full_frame', 'n/a')}%, "
         f"and the untrained Pythia-70M {(sc.get('untrained') or {}).get('json_validity', 'n/a')}% and {(sc.get('untrained') or {}).get('full_frame', 'n/a')}%. "
         f"Under the standard Locust run: p50 {g('loadtest', 'p50_ms')} ms, p95 {g('loadtest', 'p95_ms')} ms, {g('loadtest', 'rps')} requests/s, error rate {g('loadtest', 'failure_percent')}%. "
         f"Cold start median {g('coldstart', 'median_seconds')} s; rolling update failures {g('rollout', 'failure_percent')}%; pod-recovery failures {g('recovery_load', 'failure_percent')}%; "
         f"estimated cost {g('cost', 'cost_per_1000_requests')} {g('cost', 'currency', default='')} per 1,000 requests. Peak memory in the 1 CPU / 1 GiB container test: {g('docker50', 'peak_mib_cgroup')} MiB."),
        ("4. Observations",
         "The student can only be as good as the labels it is fed: the substring check removes invented slot values but cannot detect a wrong-but-present value, so teacher mistakes pass into training. "
         "A single-node k3d cluster shows self-healing, rolling updates and autoscaling, but it cannot show fault tolerance across machines because every replica shares one laptop. "
         "Readiness gating matters most at start-up: the model download dominates cold-start time."),
        ("5. What I would improve",
         "Use a larger student or more varied data, add a second-pass check of teacher labels, use dynamic batching or quantisation to cut latency, run a multi-node cluster with a PodDisruptionBudget, "
         "replace the static generated S3 keys with short-lived credentials and add TLS on the ingress, and tune requests and limits from the measured CPU and memory usage."),
    ]


def render(path, size):
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=size, leading=size * 1.28, spaceAfter=size * 0.6)
    h = ParagraphStyle("h", parent=ss["Heading2"], fontSize=size + 1.5, spaceBefore=4, spaceAfter=3)
    story = [Paragraph("<b>Written Reflection: CS3081 Cloud Computing Mini Project</b>", ParagraphStyle("t", parent=ss["Heading1"], fontSize=size + 4)),
             Paragraph(f"<b>Name:</b> Amit Sharma &nbsp;&nbsp; <b>Roll number:</b> 230103033<br/><b>GitHub repository:</b> {REPO}", body), Spacer(1, 4)]
    for title, text in sections():
        story += [Paragraph(title, h), Paragraph(text, body)]
    SimpleDocTemplate(path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                      title="Reflection 230103033", author="Amit Sharma").build(story)
    return len(PdfReader(path).pages)


def main():
    size = 12.5
    while size >= 7.5:
        if render("reflection_draft_typed.pdf", size) <= 3:
            print(f"reflection_draft_typed.pdf written (font {size} pt): print it, copy it BY HAND, scan the 3 pages to 230103033.pdf")
            if not os.path.exists("230103033.pdf"):
                shutil.copy("reflection_draft_typed.pdf", "230103033.pdf")
                print("230103033.pdf did not exist: the typed draft was copied there as a PLACEHOLDER. Replace it with your handwritten scan.")
            else:
                print("230103033.pdf already exists and was left untouched (your scan).")
            return
        size -= 0.25
    raise SystemExit("reflection does not fit in 3 pages: shorten my_notes.md")


if __name__ == "__main__":
    main()
