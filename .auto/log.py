"""Append one run to .auto/log.jsonl (same schema the pi-autoresearch tools use).

    python3 .auto/log.py --status keep --desc "adwaita pass" \
        --measure /tmp/m.txt [--asi '{"note":"..."}'] [--metric-file ...]

Reads `METRIC name=value` lines from the measure output file, uses `adwaita`
as the primary metric, keeps the rest as secondary metrics, and records the
current git HEAD as the run's commit.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "log.jsonl"


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE.parent,
                          capture_output=True, text=True).stdout.strip()


def parse_metrics(path):
    metrics, primary = {}, None
    for line in Path(path).read_text().splitlines():
        if not line.startswith("METRIC "):
            continue
        name, _, value = line[len("METRIC "):].partition("=")
        try:
            num = float(value)
        except ValueError:
            continue
        if name == "adwaita":
            primary = num
        else:
            metrics[name] = num
    if primary is None:
        raise SystemExit("no adwaita METRIC line in the measure output")
    return primary, metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", required=True)
    ap.add_argument("--status", default="keep",
                    choices=["keep", "discard", "crash", "checks_failed"])
    ap.add_argument("--desc", required=True)
    ap.add_argument("--asi", default="{}")
    args = ap.parse_args()

    primary, metrics = parse_metrics(args.measure)
    entries = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()] if LOG.exists() else []
    run = sum(1 for e in entries if "run" in e)
    configs = sum(1 for e in entries if e.get("type") == "config")
    segment = max(0, configs - 1)

    best = [e["metric"] for e in entries if e.get("status") == "keep" and "metric" in e]
    record = {
        "run": run,
        "commit": git("rev-parse", "--short=7", "HEAD"),
        "metric": primary,
        "metrics": metrics,
        "status": args.status,
        "description": args.desc,
        "timestamp": int(time.time() * 1000),
        "segment": segment,
        "confidence": None,
        "asi": json.loads(args.asi),
    }
    with LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    best_note = f"best-kept={max(best):.2f}" if best else "first run"
    print(f"logged run {run}: adwaita={primary:.2f} status={args.status} ({best_note})")


if __name__ == "__main__":
    main()
