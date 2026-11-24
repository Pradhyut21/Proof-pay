#!/usr/bin/env python
"""One-command offline smoke test: generate -> verify -> export -> import into the API -> attempt -> report.

Runs with no credentials and no network. A step that needs something unavailable is recorded as "not run" with
the reason instead of being skipped silently. Use --report-dir to select where reports are written.

    python scripts/smoke.py            # Python + Rust API
    python scripts/smoke.py --web      # also start the built Next.js app and fetch each page

Rust API binary: built with `cargo build --locked -p panelproof-api` unless PP_API_BIN points at a prebuilt one.
On Windows without a C toolchain, build/run it in WSL and set PP_API_BIN (a Linux path) plus PP_API_WSL_DISTRO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
TOKEN = "smoke-token-0123456789"


def raster_check_passed(summary: dict) -> bool:
    """The smoke needs at least one recovery, with every recovery agreeing."""
    verified = summary.get("verified", 0)
    return verified > 0 and verified == summary.get("agree_with_truth")


def step(name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"step": name, "status": status, "detail": detail})
    print(f"[{status:7}] {name}: {detail}", flush=True)


def run(cmd: list[str], env: dict | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    e["PATH"] = f"{Path.home() / '.cargo' / 'bin'}{os.pathsep}{e.get('PATH', '')}"
    return subprocess.run(cmd, check=False, cwd=ROOT, env=e, capture_output=True, text=True, timeout=timeout)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(method: str, url: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read()


def code_of(method: str, url: str, body=None, headers=None) -> int:
    try:
        return call(method, url, body, headers)[0]
    except urllib.error.HTTPError as e:
        return e.code


def wait_for(url: str, tries: int = 80) -> bool:
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def wsl_path(p: Path | str) -> str:
    s = str(p).replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:]}" if len(s) > 1 and s[1] == ":" else s


def api_command(dataset: Path, sqlite: Path, addr: str) -> tuple[list[str], dict] | None:
    distro = os.environ.get("PP_API_WSL_DISTRO")
    prebuilt = os.environ.get("PP_API_BIN")
    if distro and prebuilt:
        cmd = ["wsl.exe", "-d", distro, "-e", "env", f"PANELPROOF_REVEAL_TOKEN={TOKEN}", prebuilt, wsl_path(dataset), wsl_path(sqlite), addr]
        return cmd, {}
    if prebuilt:
        return [prebuilt, str(dataset), str(sqlite), addr], {"PANELPROOF_REVEAL_TOKEN": TOKEN}
    b = run(["cargo", "build", "--locked", "-p", "panelproof-api"])
    step("cargo build --locked -p panelproof-api", "pass" if b.returncode == 0 else "fail", (b.stderr or "").strip().splitlines()[-1][:200] if b.returncode else "ok")
    if b.returncode != 0:
        return None
    target = ROOT / os.environ.get("CARGO_TARGET_DIR", "target")
    return [str(target / "debug" / f"panelproof-api{EXE}"), str(dataset), str(sqlite), addr], {"PANELPROOF_REVEAL_TOKEN": TOKEN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--report-dir", type=Path, default=ROOT / "docs" / "results")
    args = ap.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pp-smoke-"))
    py = [sys.executable, "-m", "panelproof.cli"]
    pyenv = {"PYTHONPATH": str(ROOT / "python" / "src")}
    procs: list[subprocess.Popen] = []
    try:
        # 1. four base scenes, generated twice for a stable hash, then independently verified from pixels
        h = []
        for k in ("a", "b"):
            r = run([*py, "generate", "--seed", "smoke", "--count", "4", "--out", str(work / f"gen_{k}")], env=pyenv)
            h.append(json.loads(r.stdout)["manifest_sha256"] if r.returncode == 0 else None)
        step("generate 4 base scenes; repeated build has the same manifest hash", "pass" if h[0] and h[0] == h[1] else "fail", str(h[0]))
        r = run([*py, "verify", "--dataset", str(work / "gen_a")], env=pyenv)
        summary = json.loads(r.stdout) if r.returncode == 0 else {}
        step("raster verifier accepts scenes with zero wrong readings", "pass" if r.returncode == 0 and raster_check_passed(summary) else "fail", json.dumps(summary)[:240])

        # 2. export bundle in the shared contract and validate every record against the typed schemas
        fac = work / "bundle"
        r = run([*py, "factory", "--seed", "smoke-f", "--count", "2", "--out", str(fac)], env=pyenv)
        ok = r.returncode == 0 and (fac / "public" / "tasks.jsonl").exists() and (fac / "private" / "tasks.jsonl").exists()
        step("export contract bundle (public/tasks.jsonl, private/tasks.jsonl, images/)", "pass" if ok else "fail", (r.stdout or r.stderr).strip()[-160:])
        if not ok:
            return finish(1, work, args.keep, args.report_dir)
        check = (
            "import json,sys;from pathlib import Path;from panelproof.schemas import PublicTask,PrivateTask;"
            "b=Path(sys.argv[1]);pub=[PublicTask.model_validate_json(l) for l in (b/'public/tasks.jsonl').read_text().splitlines() if l];"
            "pri=[PrivateTask.model_validate_json(l) for l in (b/'private/tasks.jsonl').read_text().splitlines() if l];"
            "assert {p.task_id for p in pub}=={p.task_id for p in pri};print(len(pub))"
        )
        r = run([sys.executable, "-c", check, str(fac)], env=pyenv)
        step("every record validates against the typed contract", "pass" if r.returncode == 0 else "fail", (r.stdout or r.stderr).strip()[-160:])

        # 3. import into an isolated SQLite instance through the real Axum API, post a human attempt
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        spec = api_command(fac, work / "smoke.sqlite", f"127.0.0.1:{port}")
        if spec is None:
            step("API import and attempt", "not run", "Rust API could not be built here (see the cargo step)")
        else:
            cmd, extra = spec
            procs.append(subprocess.Popen(cmd, cwd=ROOT, env={**os.environ, **extra}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            if not wait_for(f"{base}/healthz"):
                step("API imports the bundle and starts", "fail", "no /healthz within 40s")
                return finish(1, work, args.keep, args.report_dir)
            step("API imports the bundle and starts", "pass", call("GET", f"{base}/healthz")[1].decode())
            page = json.loads(call("GET", f"{base}/api/v1/tasks?limit=100")[1])["items"]
            leaked = [t["task_id"] for t in page if set(t) != {"schema_version", "task_id", "image_path", "question", "public_rules", "response_schema"}]
            step("public task projection has only public fields", "pass" if page and not leaked else "fail", f"{len(page)} tasks")
            tid = page[0]["task_id"]
            priv = {json.loads(ln)["task_id"]: json.loads(ln) for ln in (fac / "private" / "tasks.jsonl").read_text().splitlines() if ln}
            png = call("GET", f"{base}/api/v1/tasks/{tid}/image")[1]
            step("served PNG matches the private SHA-256", "pass" if hashlib.sha256(png).hexdigest() == priv[tid]["image_sha256"] else "fail", tid)
            auth = {"authorization": f"Bearer {TOKEN}"}
            st, body = call("POST", f"{base}/api/v1/tasks/{tid}/reveal", headers=auth)
            answer = json.loads(body)["answer"]
            step("reveal returns the reference answer with a valid token", "pass" if st == 200 and answer == priv[tid]["answer"] else "fail", f"HTTP {st}")
            step("reveal rejects a missing/wrong token", "pass" if code_of("POST", f"{base}/api/v1/tasks/{tid}/reveal", headers={"authorization": "Bearer nope-nope-nope-nope"}) == 403 else "fail")
            hdr = {**auth, "idempotency-key": "smoke-1"}
            st, body = call("POST", f"{base}/api/v1/attempts", {"task_id": tid, "answer": answer}, hdr)
            step("human attempt with the reference answer is correct (201)", "pass" if st == 201 and json.loads(body)["correct"] else "fail", f"HTTP {st}")
            st2, _ = call("POST", f"{base}/api/v1/attempts", {"task_id": tid, "answer": answer}, hdr)
            step("same idempotency key and answer replays (200)", "pass" if st2 == 200 else "fail", f"HTTP {st2}")
            other = {"kind": "category", "value": "NORMAL"} if answer != {"kind": "category", "value": "NORMAL"} else {"kind": "category", "value": "STOPPED"}
            step("same key with a different answer conflicts (409)", "pass" if code_of("POST", f"{base}/api/v1/attempts", {"task_id": tid, "answer": other}, hdr) == 409 else "fail")
            step("malformed answer is rejected (422)", "pass" if code_of("POST", f"{base}/api/v1/attempts", {"task_id": tid, "answer": {"kind": "numeric", "value_milli": 1, "unit": "mmHg"}}, {**auth, "idempotency-key": "smoke-2"}) in (400, 422) else "fail")

            if args.web:
                web = ROOT / "apps" / "web"
                pnpm = shutil.which("pnpm")
                if not pnpm or not (web / ".next").exists():
                    step("web pages", "not run", "pnpm missing or `pnpm build` not run in apps/web")
                else:
                    wport = free_port()
                    env = {**os.environ, "PP_API_DEMO": base, "PANELPROOF_REVEAL_TOKEN": TOKEN, "PP_DEMO_DIR": str(fac)}
                    procs.append(subprocess.Popen([pnpm, "exec", "next", "start", "-H", "127.0.0.1", "-p", str(wport)], cwd=web, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    up = wait_for(f"http://127.0.0.1:{wport}/", 60)
                    urls = ("/", "/factory", "/arena", "/api/pp/demo/healthz", "/api/extras/demo/pairs")
                    codes = {p: code_of("GET", f"http://127.0.0.1:{wport}{p}") for p in urls} if up else {}
                    step("web pages and same-origin proxy respond", "pass" if up and all(v == 200 for v in codes.values()) else "fail", json.dumps(codes))
            else:
                step("web pages", "not run", "pass --web (needs `pnpm build`)")

        # 4. metrics report from a small dataset build with the offline demo adapter (labelled DEMO ONLY)
        cfg = work / "mini.yaml"
        txt = (ROOT / "configs" / "benchmark.yaml").read_text(encoding="utf-8")
        cfg.write_text(txt.replace("base_groups: 110", "base_groups: 8").replace("diagnostic_target: 40", "diagnostic_target: 3").replace("workers: 4", "workers: 2")
                       .replace("generator_config: configs/generator.yaml", f"generator_config: {(ROOT / 'configs' / 'generator.yaml').as_posix()}"), encoding="utf-8")
        ds = work / "mini"
        r = run([*py, "build-dataset", "--config", str(cfg), "--out", str(ds)], env=pyenv)
        step("build a small dataset (8 base groups)", "pass" if r.returncode == 0 else "fail", (r.stderr or r.stdout).strip()[-160:])
        if r.returncode == 0:
            att = work / "attempts.jsonl"
            r = run([*py, "demo-attempts", "--dataset", str(ds), "--out", str(att)], env=pyenv)
            r2 = run([*py, "metrics", "--tasks", str(ds), "--attempts", str(att), "--out", str(work / "report")], env=pyenv)
            md = work / "report" / "report.md"
            labelled = md.exists() and "DEMO ONLY" in md.read_text(encoding="utf-8")
            step("report generated and labelled DEMO ONLY", "pass" if r.returncode == 0 and r2.returncode == 0 and labelled else "fail", (r2.stderr or "").strip()[-160:])
            if md.exists():
                shutil.copyfile(md, args.report_dir / "smoke_report_demo.md")
        return finish(0, work, args.keep, args.report_dir)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def finish(code: int, work: Path, keep: bool, report_dir: Path) -> int:
    failed = [r for r in RESULTS if r["status"] == "fail"]
    out = report_dir / "smoke_report.json"
    counts = {s: sum(1 for r in RESULTS if r["status"] == s) for s in ("pass", "fail", "not run")}
    payload = {
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
                        "api_bin": os.environ.get("PP_API_BIN"), "api_wsl_distro": os.environ.get("PP_API_WSL_DISTRO")},
        "counts": counts,
        "steps": RESULTS,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nsmoke: {counts}; report -> {out}")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else code


if __name__ == "__main__":
    sys.exit(main())
