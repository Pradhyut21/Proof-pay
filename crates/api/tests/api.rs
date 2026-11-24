use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use pp_api::{build_app, new_state, valid_seed, verify_worker_output, Config};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{path::PathBuf, time::Duration};
use tower::ServiceExt;

const IMG: &str = "im_0123456789abcdef.png";

fn write_root(dir: &std::path::Path, with_manifest: bool, bad_hash: bool) {
    std::fs::create_dir_all(dir.join("images")).unwrap();
    let png = b"\x89PNG\r\n\x1a\nfake";
    std::fs::write(dir.join("images").join(IMG), png).unwrap();
    let task = json!({
        "schema_version": "1.0.0", "task_id": "t_1", "image": format!("images/{IMG}"),
        "question": "q?", "rules": "r", "set": "main",
        "response_schema": {"type": "category", "allowed": ["NORMAL", "STOPPED"]},
        "seed": "SECRET-SEED", "answer": {"kind": "category", "value": "NORMAL"}
    });
    std::fs::write(dir.join("tasks.jsonl"), format!("{task}\n")).unwrap();
    let key = json!({"task_id": "t_1", "answer": {"kind": "category", "value": "NORMAL"},
        "variant_kind": "base", "skill": "M", "kind": "state", "evidence": [{"kind": "module"}]});
    std::fs::write(dir.join("sample_keys.jsonl"), format!("{key}\n")).unwrap();
    if with_manifest {
        let h = |b: &[u8]| format!("{:x}", Sha256::digest(b));
        let img_h = if bad_hash { "0".repeat(64) } else { h(png) };
        let tasks_h = h(&std::fs::read(dir.join("tasks.jsonl")).unwrap());
        let m = json!({"files": {format!("images/{IMG}"): img_h, "tasks.jsonl": tasks_h}});
        std::fs::write(dir.join("manifest.json"), m.to_string()).unwrap();
    }
}

fn app(dir: &std::path::Path, token: Option<&str>) -> axum::Router {
    let cfg = Config {
        data_dir: dir.to_path_buf(),
        runs_dir: dir.join("runs"),
        repo_root: PathBuf::from("."),
        python: "python".into(),
        reveal_token: token.map(String::from),
        allowed_origins: vec!["http://localhost:3000".into()],
        job_deadline: Duration::from_secs(5),
        max_count: 4,
    };
    build_app(new_state(cfg).unwrap())
}

async fn call(app: &axum::Router, req: Request<Body>) -> (StatusCode, Vec<u8>) {
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    (
        status,
        resp.into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .to_vec(),
    )
}

fn get(uri: &str) -> Request<Body> {
    Request::get(uri).body(Body::empty()).unwrap()
}

fn post(uri: &str, body: Value) -> Request<Body> {
    Request::post(uri)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap()
}

#[tokio::test]
async fn health_and_capabilities() {
    let d = tempdir("health");
    write_root(&d, false, false);
    let a = app(&d, None);
    let (s, b) = call(&a, get("/health")).await;
    assert_eq!(s, StatusCode::OK);
    let v: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(v["status"], "ok");
    assert_eq!(v["tasks_loaded"], 1);
    let (_, b) = call(&a, get("/v1/capabilities")).await;
    let v: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(v["reveal_enabled"], false);
    assert_eq!(v["live_models"], false);
}

#[tokio::test]
async fn public_projection_never_leaks_private_fields() {
    let d = tempdir("proj");
    write_root(&d, false, false);
    let a = app(&d, None);
    let (_, b) = call(&a, get("/v1/tasks")).await;
    let text = String::from_utf8(b).unwrap();
    assert!(
        !text.contains("SECRET-SEED") && !text.contains("\"answer\""),
        "{text}"
    );
    let (_, b) = call(&a, get("/v1/tasks/t_1")).await;
    let v: Value = serde_json::from_slice(&b).unwrap();
    let mut keys: Vec<_> = v.as_object().unwrap().keys().cloned().collect();
    keys.sort();
    assert_eq!(
        keys,
        [
            "image",
            "question",
            "response_schema",
            "rules",
            "schema_version",
            "set",
            "task_id"
        ]
    );
}

#[tokio::test]
async fn images_are_served_safely() {
    let d = tempdir("img");
    write_root(&d, false, false);
    let a = app(&d, None);
    let (s, b) = call(&a, get(&format!("/v1/images/{IMG}"))).await;
    assert_eq!(s, StatusCode::OK);
    assert!(b.starts_with(b"\x89PNG"));
    for bad in [
        "..%2F..%2FCargo.toml",
        "im_ZZZZ.png",
        "im_0123456789abcde.png",
        "notes.txt",
    ] {
        let (s, _) = call(&a, get(&format!("/v1/images/{bad}"))).await;
        assert!(
            s == StatusCode::BAD_REQUEST || s == StatusCode::NOT_FOUND,
            "{bad} -> {s}"
        );
    }
    let (s, _) = call(&a, get("/v1/images/im_ffffffffffffffff.png")).await;
    assert_eq!(s, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn attempts_are_scored_and_reveal_is_gated() {
    let d = tempdir("att");
    write_root(&d, false, false);
    let a = app(&d, Some("tok"));
    let ok = json!({"task_id": "t_1", "response": {"kind": "category", "value": "NORMAL"}});
    let (_, b) = call(&a, post("/v1/attempts", ok)).await;
    assert_eq!(
        serde_json::from_slice::<Value>(&b).unwrap()["outcome"],
        "correct"
    );
    let bad =
        json!({"task_id": "t_1", "response": {"kind": "numeric", "value_milli": 1, "unit": "kPa"}});
    let (_, b) = call(&a, post("/v1/attempts", bad)).await;
    assert_eq!(
        serde_json::from_slice::<Value>(&b).unwrap()["outcome"],
        "invalid"
    );
    let (s, _) = call(
        &a,
        post("/v1/attempts", json!({"task_id": "nope", "response": {}})),
    )
    .await;
    assert_eq!(s, StatusCode::NOT_FOUND);
    let (s, _) = call(&a, post("/v1/tasks/t_1/reveal", json!({}))).await;
    assert_eq!(s, StatusCode::FORBIDDEN);
    let req = Request::post("/v1/tasks/t_1/reveal")
        .header("x-panelproof-token", "tok")
        .body(Body::empty())
        .unwrap();
    let (s, b) = call(&a, req).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&b).unwrap()["answer"]["value"],
        "NORMAL"
    );
    let no_token = app(&d, None);
    let (s, _) = call(&no_token, post("/v1/tasks/t_1/reveal", json!({}))).await;
    assert_eq!(s, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn oversized_bodies_and_bad_job_requests_are_rejected() {
    let d = tempdir("lim");
    write_root(&d, false, false);
    let a = app(&d, None);
    let big = json!({"task_id": "t_1", "response": {"pad": "x".repeat(20_000)}});
    let (s, _) = call(&a, post("/v1/attempts", big)).await;
    assert_eq!(s, StatusCode::PAYLOAD_TOO_LARGE);
    for body in [
        json!({"seed": "ok", "count": 0}),
        json!({"seed": "ok", "count": 99}),
        json!({"seed": "a b", "count": 1}),
    ] {
        let (s, _) = call(&a, post("/v1/jobs/generate", body)).await;
        assert_eq!(s, StatusCode::BAD_REQUEST);
    }
    assert!(valid_seed("demo-1_a") && !valid_seed("") && !valid_seed("../x"));
}

#[test]
fn malformed_or_tampered_worker_output_is_rejected() {
    let d = tempdir("w1");
    write_root(&d, true, false);
    assert!(verify_worker_output(&d).is_ok());
    let d = tempdir("w2");
    write_root(&d, true, true);
    assert!(verify_worker_output(&d)
        .unwrap_err()
        .contains("hash mismatch"));
    let d = tempdir("w3");
    write_root(&d, false, false);
    assert!(verify_worker_output(&d)
        .unwrap_err()
        .contains("manifest missing"));
    let d = tempdir("w4");
    write_root(&d, true, false);
    std::fs::write(d.join("manifest.json"), "{not json").unwrap();
    assert!(verify_worker_output(&d).unwrap_err().contains("malformed"));
    let d = tempdir("w5");
    write_root(&d, true, false);
    std::fs::write(
        d.join("manifest.json"),
        json!({"files": {"../x": "00"}}).to_string(),
    )
    .unwrap();
    assert!(verify_worker_output(&d).unwrap_err().contains("escapes"));
}

fn tempdir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("pp_api_test_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}
