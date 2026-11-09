# AI use

**Tools:** Claude (Anthropic), through the Claude app and Claude Code sessions. No other AI tool was used.

**What it was used for**
- Drafting the starting code and files of this repository: worker, clean.py, training and evaluation scripts, FastAPI service and Dockerfile, Kubernetes manifests, NACL file and subnet working, Makefile, CI workflow, evidence scripts, tests, and the report draft.
- Helping me run and debug the pipeline: finding why labelling stalled (Ollama hang, GPU not usable, storage outage), adding worker retries and checkpoint resume, changing the teacher request options, tuning Ollama for CPU, fixing a CI lint error, and fixing the deployment failures (one generation at a time per pod, probe timeouts, rollback check, shutdown pause, pod warm-up).
- Explaining results and comparing them with the limits in the assignment.

**What I did myself**
- Ran every stage on my own laptop (Windows 11, WSL2, k3d), watched the long runs for days, and re-ran the stages that failed.
- Chose the number of training epochs, kept the failed runs instead of deleting them, and checked the results against the limits in the assignment.
- Wrote and scanned the handwritten reflection.

**How the output was checked**
- Unit tests (33), ruff lint, the NACL simulator check, and the CI workflow (lint, tests, model evaluation, quality gate, gitleaks); logs are in results/ and in GitHub Actions.
- All measured numbers (labels, losses, validation scores, load tests, Kubernetes behaviour) come from running the pipeline on my own laptop; the report builder reads them from results/. No result was typed in by hand or written by the AI.
- Earlier failed attempts are in results/attempts/ and explained in section 8 of the report. Teacher replies were stored exactly as generated and not edited.
- Subnet table recomputed from usable = 2^(32 - prefix) - 2.
