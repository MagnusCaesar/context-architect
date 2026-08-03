#!/usr/bin/env python3
"""fm-review.py — walk the first-mate registry and run each project's existing
hygiene/reachability/validate scripts. Read-only; never mutates project state."""
import argparse, json, subprocess, sys
from pathlib import Path

from context_utils import firstmate_root, registered_projects

def parse_registry(reg: Path):
    """Yield (name, context_path) from <article class="project">name | path | ...</article>."""
    for name, path, _summary, _status in registered_projects(reg.parent, reg):
        yield name, path

def run_json(script: Path, ctx: Path, extra=("--json",)):
    """Run a context script from inside ctx, return parsed JSON or an error dict."""
    if not script.exists():
        return {"status": "missing-script"}
    try:
        r = subprocess.run([sys.executable, str(script), *extra],
                           cwd=str(ctx), capture_output=True, text=True, timeout=120)
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {"status": "no-output"}
        except json.JSONDecodeError:
            return {"status": "ok" if r.returncode == 0 else "fail",
                    "raw": r.stdout.strip()[:400]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}

def validate_failures(ctx: Path):
    v = ctx / "scripts" / "validate.py"
    if not v.exists():
        return ["missing-validate"]
    try:
        r = subprocess.run([sys.executable, str(v)], cwd=str(ctx),
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return ["timeout"]
    return [ln for ln in r.stdout.splitlines() if ln.strip().startswith("FAIL")]


def short_status(result: dict) -> str:
    status = result.get("status")
    return status if isinstance(status, str) and status else "unknown"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firstmate", default=str(firstmate_root()))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    fm_ctx = Path(args.firstmate) / "context"
    reg = fm_ctx / "project-registry.html"
    report = {"projects": [], "dead_paths": []}
    for name, cpath in parse_registry(reg):
        ctx = Path(cpath)
        if not (ctx / "index.html").exists():
            report["dead_paths"].append({"name": name, "path": cpath})
            continue
        scripts = ctx / "scripts"
        hygiene = short_status(run_json(scripts / "daily-hygiene.py", ctx))
        reachability = short_status(run_json(scripts / "check-reachability.py", ctx))
        failures = len(validate_failures(ctx))
        status = "ok" if hygiene == "ok" and reachability == "ok" and failures == 0 else "issues"
        report["projects"].append({"name": name, "path": cpath, "status": status,
                                   "hygiene": hygiene, "reachability": reachability,
                                   "validation": "ok" if failures == 0 else f"{failures} failures"})

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for p in report["projects"]:
            print(f"{p['name']}: {p['status']} | validate {p['validation']} | "
                  f"hygiene {p['hygiene']} | reach {p['reachability']}")
        for d in report["dead_paths"]:
            print(f"DEAD: {d['name']} -> {d['path']}")

if __name__ == "__main__":
    main()
