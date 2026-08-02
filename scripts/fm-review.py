#!/usr/bin/env python3
"""fm-review.py — walk the first-mate registry and run each project's existing
hygiene/reachability/validate scripts. Read-only; never mutates project state."""
import argparse, json, os, re, subprocess, sys
from pathlib import Path

def parse_registry(reg: Path):
    """Yield (name, context_path) from <article class="project">name | path | ...</article>."""
    if not reg.exists():
        return
    html = reg.read_text(errors="replace")
    for m in re.finditer(r'<article[^>]*class="project"[^>]*>(.*?)</article>', html, re.S):
        text = re.sub(r"<[^>]*>", "", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        parts = [p.strip() for p in text.split("|")]
        if len(parts) >= 2:
            yield parts[0], parts[1]

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firstmate", default=os.path.expanduser("~/.claude/firstmate"))
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
        report["projects"].append({
            "name": name, "path": cpath,
            "hygiene": run_json(scripts / "daily-hygiene.py", ctx),
            "reachability": run_json(scripts / "check-reachability.py", ctx),
            "validate_failures": validate_failures(ctx),
        })

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for p in report["projects"]:
            nfail = len(p["validate_failures"])
            print(f"{p['name']}: validate {'OK' if nfail == 0 else str(nfail)+' FAIL'} | "
                  f"hygiene {p['hygiene'].get('status','?')} | "
                  f"reach {p['reachability'].get('status','?')}")
        for d in report["dead_paths"]:
            print(f"DEAD: {d['name']} -> {d['path']}")

if __name__ == "__main__":
    main()
