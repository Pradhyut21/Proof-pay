use std::fs;
use std::path::Path;

use axum::body::{to_bytes, Body};
use axum::http::{header, Request, StatusCode};
use axum::Router;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::{tempdir, TempDir};
use tower::ServiceExt;

const TOKEN: &str = "fixture-only-local-token";
fn encode_png(red: u8) -> Vec<u8> {
    let mut image = Vec::new();
    let mut encoder = png::Encoder::new(&mut image, 1, 1);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().unwrap();
    writer.write_image_data(&[red, 42, 42]).unwrap();
    writer.finish().unwrap();
    image
}

fn write_bundle(root: &Path) {
    for path in ["public", "private", "images"] {
        fs::create_dir(root.join(path)).unwrap();
    }
    let mut public = Vec::new();
    let mut private = Vec::new();
    for (id, split, image) in [
        ("A-dev", "dev", encode_png(42)),
        ("B-frozen", "test_frozen", encode_png(64)),
    ] {
        let image_path = format!("images/{id}.png");
        fs::write(root.join(&image_path), &image).unwrap();
        let hash = format!("{:x}", Sha256::digest(&image));
        public.push(json!({
            "schema_version": "1.0.0", "task_id": id, "image_path": image_path,
            "question": "What is the state?", "public_rules": "Use the public pump rule.",
            "response_schema": {"type": "object"},
        }));
        private.push(json!({
            "schema_version": "1.0.0", "task_id": id, "base_scene_id": id, "group_id": id,
            "variant_kind": "original", "split": split, "skill": "operational_state",
            "difficulty": {}, "answer": {"kind": "category", "value": "NORMAL"},
            "evidence_regions": [{"instrument_id": "P1", "x": 0, "y": 0, "width": 1, "height": 1}],
            "solver_version": "fixture", "image_sha256": hash, "validation_status": "accepted",
        }));
    }
    for (path, records) in [
        ("public/tasks.jsonl", public),
        ("private/tasks.jsonl", private),
    ] {
        let content = records
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n");
        fs::write(root.join(path), content).unwrap();
    }
}

async fn local_service() -> (TempDir, Router) {
    let root = tempdir().unwrap();
    write_bundle(root.path());
    let app = panelproof_api::open(
        root.path(),
        &root.path().join("runs.sqlite"),
        Some(TOKEN.into()),
    )
    .await
    .unwrap();
    (root, app)
}

async fn send(
    app: &Router,
    method: &str,
    uri: &str,
    token: bool,
    input: Option<(&str, Value)>,
) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
    let mut req = Request::builder().method(method).uri(uri);
    if token {
        req = req.header(header::AUTHORIZATION, format!("Bearer {TOKEN}"));
    }
    let body = match input {
        Some((key, value)) => {
            req = req
                .header("idempotency-key", key)
                .header(header::CONTENT_TYPE, "application/json");
            Body::from(value.to_string())
        }
        None => Body::empty(),
    };
    let response = app.clone().oneshot(req.body(body).unwrap()).await.unwrap();
    let (head, body) = response.into_parts();
    (
        head.status,
        head.headers,
        to_bytes(body, 1024 * 1024).await.unwrap().to_vec(),
    )
}

#[tokio::test]
async fn public_routes_and_reveal_respect_visibility() {
    let (_root, app) = local_service().await;
    assert_eq!(
        send(&app, "GET", "/healthz", false, None).await.0,
        StatusCode::OK
    );
    let (status, _, data) = send(&app, "GET", "/api/v1/tasks?limit=1", false, None).await;
    assert_eq!(status, StatusCode::OK);
    let page: Value = serde_json::from_slice(&data).unwrap();
    assert_eq!(page["next_cursor"], "A-dev");
    assert_eq!(page["items"][0].as_object().unwrap().len(), 6);
    assert!(page["items"][0].get("answer").is_none());
    let (status, headers, data) = send(&app, "GET", "/api/v1/tasks/A-dev/image", false, None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers[header::CONTENT_TYPE], "image/png");
    assert_eq!(data, encode_png(42));
    for (id, token) in [("A-dev", false), ("B-frozen", true)] {
        let uri = format!("/api/v1/tasks/{id}/reveal");
        assert_eq!(
            send(&app, "POST", &uri, token, None).await.0,
            StatusCode::FORBIDDEN
        );
    }
    let (status, _, data) = send(&app, "POST", "/api/v1/tasks/A-dev/reveal", true, None).await;
    assert_eq!(status, StatusCode::OK);
    let reveal: Value = serde_json::from_slice(&data).unwrap();
    assert_eq!(reveal["answer"]["value"], "NORMAL");
    assert!(reveal.get("image_sha256").is_none());
    assert_eq!(
        send(&app, "GET", "/api/v1/tasks?limit=1000", false, None)
            .await
            .0,
        StatusCode::BAD_REQUEST
    );
}

#[tokio::test]
async fn human_answer_is_idempotent_and_frozen_tasks_cannot_be_probed() {
    let (root, app) = local_service().await;
    let normal = json!({"task_id": "A-dev", "answer": {"kind": "category", "value": "NORMAL"}});
    let stopped = json!({"task_id": "A-dev", "answer": {"kind": "category", "value": "STOPPED"}});
    let frozen = json!({"task_id": "B-frozen", "answer": {"kind": "category", "value": "NORMAL"}});
    let uri = "/api/v1/attempts";
    let result = send(&app, "POST", uri, true, Some(("request-1", normal.clone()))).await;
    assert_eq!(result.0, StatusCode::CREATED);
    assert_eq!(
        serde_json::from_slice::<Value>(&result.2).unwrap()["correct"],
        true
    );
    drop(app);
    let reopened = panelproof_api::open(
        root.path(),
        &root.path().join("runs.sqlite"),
        Some(TOKEN.into()),
    )
    .await
    .unwrap();
    assert_eq!(
        send(&reopened, "POST", uri, true, Some(("request-1", normal)))
            .await
            .0,
        StatusCode::OK
    );
    assert_eq!(
        send(&reopened, "POST", uri, true, Some(("request-1", stopped)))
            .await
            .0,
        StatusCode::CONFLICT
    );
    assert_eq!(
        send(&reopened, "POST", uri, true, Some(("request-2", frozen)))
            .await
            .0,
        StatusCode::FORBIDDEN
    );
}

#[tokio::test]
async fn malformed_or_changed_artifacts_are_rejected() {
    let (root, app) = local_service().await;
    fs::write(root.path().join("images/A-dev.png"), b"not a PNG").unwrap();
    assert_eq!(
        send(&app, "GET", "/api/v1/tasks/A-dev/image", false, None)
            .await
            .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let db = root.path().join("other.sqlite");
    assert!(panelproof_api::open(root.path(), &db, None).await.is_err());
    assert!(!db.exists());
    fs::write(root.path().join("images/A-dev.png"), encode_png(42)).unwrap();
    let path = root.path().join("public/tasks.jsonl");
    let original = fs::read_to_string(&path).unwrap();
    fs::write(
        &path,
        original.replace("images/A-dev.png", "images/../A-dev.png"),
    )
    .unwrap();
    assert!(panelproof_api::open(root.path(), &db, None).await.is_err());
    fs::write(
        &path,
        original.replace("{\"image_path\"", "{\"answer\":\"private\",\"image_path\""),
    )
    .unwrap();
    assert!(panelproof_api::open(root.path(), &db, None).await.is_err());
}

#[tokio::test]
async fn import_rejects_truncated_png_even_with_matching_hash() {
    let root = tempdir().unwrap();
    write_bundle(root.path());
    let image = encode_png(42);
    let truncated = &image[..33];
    fs::write(root.path().join("images/A-dev.png"), truncated).unwrap();
    let path = root.path().join("private/tasks.jsonl");
    let original = fs::read_to_string(&path).unwrap();
    let updated = original.replace(
        &format!("{:x}", Sha256::digest(&image)),
        &format!("{:x}", Sha256::digest(truncated)),
    );
    fs::write(&path, updated).unwrap();
    let response = panelproof_api::open(root.path(), &root.path().join("runs.sqlite"), None).await;
    assert!(response
        .err()
        .unwrap()
        .to_string()
        .contains("truncated PNG"));
}

#[tokio::test]
async fn import_rejects_group_overlap_between_dev_and_frozen() {
    let root = tempdir().unwrap();
    write_bundle(root.path());
    let path = root.path().join("private/tasks.jsonl");
    let original = fs::read_to_string(&path).unwrap();
    let updated = original.replace("\"group_id\":\"B-frozen\"", "\"group_id\":\"A-dev\"");
    fs::write(path, updated).unwrap();
    let response = panelproof_api::open(root.path(), &root.path().join("runs.sqlite"), None).await;
    assert!(response
        .err()
        .unwrap()
        .to_string()
        .contains("share group_id"));
}
