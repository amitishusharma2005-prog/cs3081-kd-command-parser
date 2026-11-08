import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("summ", os.path.join(ROOT, "scripts", "summarize.py"))
summ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summ)

# Parser fixtures are synthetic text in the exact formats the scripts/tools print; they are NOT results.


def test_coldstart_parser_takes_slowest_pod_and_median():
    t = ("run 1 pod/a created=x ready=y seconds=10\nrun 1 pod/b created=x ready=y seconds=12\n"
         "run 2 pod/a created=x ready=y seconds=9\nrun 3 pod/a created=x ready=y seconds=20\n")
    r = summ.coldstart(t)
    assert r["per_run_seconds"] == {1: 12, 2: 9, 3: 20} and r["median_seconds"] == 12


def test_hpa_parser_detects_up_and_down():
    pre = "horizontalpodautoscaler.autoscaling/"
    rows = ["command-parser-hpa   Deployment/command-parser   3%/70%   1   2   1   5m",
            pre + "command-parser-hpa   Deployment/command-parser   90%/70%   1   2   2   6m",
            pre + "command-parser-hpa   Deployment/command-parser   cpu: 2%/70%   1   2   1   16m"]
    r = summ.hpa("\n".join(rows))
    assert r["scaled_up_1_to_2"] and r["scaled_back_to_1"] and r["max_replicas_seen"] == 2


def test_docker50_and_top_parsers():
    d = summ.docker50("ok=50/50\nOOMKilled: false\npeak memory (cgroup): 1048576\nrequest 1 -> HTTP 200, mem 300MiB\n")
    assert d["ok"] == 50 and d["oom_killed"] == "false" and d["peak_mib_cgroup"] == 1.0
    assert summ.top("NAME CPU MEM\ncommand-parser-abc-1 680m 432Mi\n")[0]["cpu"] == "680m"
