# AI use

**Tool:** Claude (Anthropic) was used to draft the code, manifests, tests, CI workflow, scripts and documentation in this repository.

**What it did:** wrote the worker, `clean.py`, training/evaluation scripts, the FastAPI service and Dockerfile, the Kubernetes manifests, the NACL file and subnet working, the Makefile, CI workflow, evidence-collection scripts and tests.

**How the output was checked:**
- `tools/nacl_sim.py --check` on the sample packets (6/6) and 15 extra hand-chosen packets in `tests/test_all.py`.
- `pytest` (all tests in `tests/`: `clean.py` rules (a)-(e), service endpoints/headers/validation/`FAULT_INJECT`, NACL, `score.py`, prompt masking, log parsers). Log: `results/pytest_output.log`.
- Subnet table recomputed from the formula usable = 2^(32-prefix) - 2.
- Measured results (labels, loss, scores, load tests, Kubernetes behaviour) come only from running the pipeline on my own machine; none were written by the AI.
- Reviewed: I read the generated manifests and code and adjusted them where my environment differed.
