#!/usr/bin/env python
"""One-command smoke test: generate -> verify -> export -> API -> human attempt -> report.

Everything runs locally and offline. Steps that need an unavailable tool are recorded as "not run" with
the reason instead of being silently skipped. Writes docs/results/smoke_report.json.

    python scripts/smoke.py [--web]        # --web additionally starts `next start` and fetches each page
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ".exe" if os.name == "nt" else ""
RESULTS: list[dict] = []


def step(name: str, status: str, detail: str = "", **extra) -> None:
    RESULTS.append({"step": name, "status": status, "detail": detail, **extra})
    print(f"[{status:7}] {name}: {detail}", flush=True)


def run(cmd: list[str], cwd: Path = ROOT, env: dict | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    cargo_bin = Path.home() / ".cargo" / "bin"
    e["PATH"] = f"{cargo_bin}{os.pathsep}{e.get('PATH', '')}"
    return subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"content-type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode() or "null")


def wait_for(url: str, tries: int = 60) -> bool:
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", action="store_true", help="also start the built Next.js app")
    ap.add_argument("--keep", action="store_true", help="keep the temp work directory")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pp-smoke-"))
    py = [sys.executable, "-m", "panelproof.cli"]
    pyenv = {"PYTHONPATH": str(ROOT / "python" / "src")}
    procs: list[subprocess.Popen] = []
    try:
        # 1. generate + independent raster verification
        gen = work / "gen"
        r = run([*py, "generate", "--seed", "smoke", "--count", "4", "--out", str(gen)], env=pyenv)
        step("generate 4 base scenes", "pass" if r.returncode == 0 else "fail", (r.stdout or r.stderr).strip()[-200:])
        if r.returncode != 0:
            return finish(1, work, args.keep)
        r = run([*py, "verify", "--dataset", str(gen)], env=pyenv)
        summary = json.loads(r.stdout) if r.returncode == 0 else {}
        wrong = summary.get("wrong", summary.get("accepted_wrong", None))
        step("verify rasters independently", "pass" if r.returncode == 0 and not wrong else "fail", json.dumps(summary)[:300])

        # 2. factory export (tasks, private keys, pairs, attempts, manifest)
        fac = work / "factory"
        r = run([*py, "factory", "--seed", "smoke-f", "--count", "2", "--out", str(fac)], env=pyenv)
        ok = r.returncode == 0 and (fac / "tasks.jsonl").exists() and (fac / "manifest.json").exists()
        step("export task bundle", "pass" if ok else "fail", (r.stdout or r.stderr).strip()[-200:])
        if not ok:
            return finish(1, work, args.keep)

        # 3. Rust build + API
        if shutil.which("cargo") is None and not (Path.home() / ".cargo" / "bin" / f"cargo{EXE}").exists():
            step("cargo build + API", "not run", "cargo is not installed")
        else:
            b = run(["cargo", "build", "-p", "pp-api", "--locked"], timeout=1800)
            step("cargo build -p pp-api", "pass" if b.returncode == 0 else "fail", b.stderr.strip()[-200:])
            if b.returncode == 0:
                port = free_port()
                env = {
                    **os.environ,
                    "PP_BIND": f"127.0.0.1:{port}",
                    "PP_DATA_DIR": str(fac),
                    "PP_RUNS_DIR": str(work / "runs"),
                    "PP_REPO_ROOT": str(ROOT),
                    "PP_REVEAL_TOKEN": "smoke-token",
                    "PP_PYTHON": sys.executable,
                    "PYTHONPATH": str(ROOT / "python" / "src"),
                }
                procs.append(subprocess.Popen([str(ROOT / "target" / "debug" / f"pp-api{EXE}")], cwd=ROOT, env=env))
                base = f"http://127.0.0.1:{port}"
                if not wait_for(f"{base}/health"):
                    step("API starts", "fail", "no /health within 30s")
                    return finish(1, work, args.keep)
                health = http("GET", f"{base}/health")
                step("API starts", "pass", json.dumps(health))
                tasks = http("GET", f"{base}/v1/tasks")
                leaked = [t for t in tasks if "answer" in json.dumps(t).lower().replace("response_schema", "")]
                step("public tasks hide answers", "pass" if tasks and not leaked else "fail", f"{len(tasks)} tasks")
                task = tasks[0]
                # reveal with token, answer correctly through the API
                rev = http("POST", f"{base}/v1/tasks/{task['task_id']}/reveal", headers={"x-panelproof-token": "smoke-token"})
                got = http("POST", f"{base}/v1/attempts", {"task_id": task["task_id"], "response": rev["answer"]})
                step("human attempt (correct) scores correct", "pass" if got["outcome"] == "correct" else "fail", got["outcome"])
                bad = http("POST", f"{base}/v1/attempts", {"task_id": task["task_id"], "response": {"kind": "bogus"}})
                step("malformed attempt scores invalid", "pass" if bad["outcome"] == "invalid" else "fail", bad["outcome"])
                try:
                    http("POST", f"{base}/v1/tasks/{task['task_id']}/reveal", headers={"x-panelproof-token": "wrong"})
                    step("reveal rejects a bad token", "fail", "accepted")
                except urllib.error.HTTPError as e:
                    step("reveal rejects a bad token", "pass" if e.code in (401, 403) else "fail", f"HTTP {e.code}")
                # fresh generation job through the API worker
                job = http("POST", f"{base}/v1/jobs/generate", {"seed": "smoke-job", "count": 1, "difficulty": "easy"})
                for _ in range(120):
                    j = http("GET", f"{base}/v1/jobs/{job['job_id']}")
                    if j["status"] in ("succeeded", "failed"):
                        break
                    time.sleep(1)
                step("generation job completes", "pass" if j["status"] == "succeeded" else "fail", j["status"])

                # 4. optional web
                if args.web:
                    web = ROOT / "apps" / "web"
                    pnpm = shutil.which("pnpm")
                    if not pnpm or not (web / ".next").exists():
                        step("web pages", "not run", "pnpm missing or `pnpm build` not run")
                    else:
                        wport = free_port()
                        wenv = {**os.environ, "NEXT_PUBLIC_PP_API": base}
                        procs.append(subprocess.Popen([pnpm, "exec", "next", "start", "-H", "127.0.0.1", "-p", str(wport)], cwd=web, env=wenv))
                        okw = wait_for(f"http://127.0.0.1:{wport}/", 60)
                        codes = {}
                        for p in ("/", "/factory", "/arena"):
                            try:
                                codes[p] = urllib.request.urlopen(f"http://127.0.0.1:{wport}{p}", timeout=10).status
                            except OSError as e:
                                codes[p] = str(e)
                        step("web pages respond", "pass" if okw and all(v == 200 for v in codes.values()) else "fail", json.dumps(codes))
                else:
                    step("web pages", "not run", "pass --web (needs `pnpm build`)")

        # 5. report
        att = work / "attempts.jsonl"
        r = run([*py, "demo-attempts", "--dataset", str(fac), "--out", str(att)], env=pyenv)
        step("offline demo attempts", "pass" if r.returncode == 0 else "fail", r.stdout.strip()[-160:])
        if r.returncode == 0:
            r = run([*py, "metrics", "--tasks", str(fac), "--attempts", str(att), "--out", str(work / "report")], env=pyenv)
            md = work / "report" / "report.md"
            labeled = md.exists() and "DEMO ONLY" in md.read_text(encoding="utf-8")
            step("report generated and labelled DEMO ONLY", "pass" if r.returncode == 0 and labeled else "fail", r.stderr.strip()[-200:])
        return finish(0, work, args.keep)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def finish(code: int, work: Path, keep: bool) -> int:
    failed = [r for r in RESULTS if r["status"] == "fail"]
    out = ROOT / "docs" / "results" / "smoke_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"python": sys.version.split()[0], "platform": sys.platform, "steps": RESULTS, "failed": len(failed)}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nsmoke: {len(RESULTS)} steps, {len(failed)} failed, report -> {out.relative_to(ROOT)}")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else code


if __name__ == "__main__":
    sys.exit(main())
