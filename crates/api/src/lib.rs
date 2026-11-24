//! PanelProof local API (INTERIM fixture service for PP-15/PP-17).
//!
//! PP-14 owns the production service (SQLx/SQLite job state, full contract). This crate serves the
//! public task projection, scores human attempts with `pp-scoring`, gates evidence reveal, runs
//! bounded Python generation jobs, and validates worker output hashes before publishing it.

use axum::{
    extract::{DefaultBodyLimit, Path, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    path::{Path as FsPath, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, RwLock, Semaphore};

pub const PUBLIC_KEYS: [&str; 7] = [
    "schema_version",
    "task_id",
    "image",
    "question",
    "rules",
    "response_schema",
    "set",
];
const MAX_BODY: usize = 16 * 1024;
const MAX_TASKS: usize = 5000;
const MAX_IMAGE_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone)]
pub struct Config {
    pub data_dir: PathBuf,
    pub runs_dir: PathBuf,
    pub repo_root: PathBuf,
    pub python: String,
    pub reveal_token: Option<String>,
    pub allowed_origins: Vec<String>,
    pub job_deadline: Duration,
    pub max_count: u32,
}

#[derive(Default)]
pub struct Store {
    tasks: BTreeMap<String, Value>,
    keys: HashMap<String, Value>,
    pairs: Vec<Value>,
    model_attempts: HashMap<String, Vec<Value>>,
    images: HashMap<String, PathBuf>,
    attempts: Vec<Value>,
}

#[derive(Clone, Debug)]
struct Job {
    id: String,
    key: String,
    status: &'static str,
    started: Instant,
    error: Option<String>,
    task_ids: Vec<String>,
}

pub struct AppState {
    pub cfg: Config,
    pub store: RwLock<Store>,
    jobs: Mutex<HashMap<String, Job>>,
    gate: Semaphore,
    counter: AtomicU64,
}

pub type Shared = Arc<AppState>;

type ApiResult<T> = Result<Json<T>, (StatusCode, Json<Value>)>;

fn err(code: StatusCode, msg: &str) -> (StatusCode, Json<Value>) {
    (code, Json(json!({ "error": msg })))
}

fn sha256_file(p: &FsPath) -> std::io::Result<String> {
    let bytes = std::fs::read(p)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn read_jsonl(p: &FsPath) -> Result<Vec<Value>, String> {
    let raw = std::fs::read_to_string(p).map_err(|e| format!("{}: {e}", p.display()))?;
    raw.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str::<Value>(l).map_err(|e| format!("{}: {e}", p.display())))
        .collect()
}

/// Allowlisted public projection: only schema-listed keys ever leave the server.
pub fn project_public(task: &Value) -> Value {
    let mut out = serde_json::Map::new();
    for k in PUBLIC_KEYS {
        if let Some(v) = task.get(k) {
            out.insert(k.to_string(), v.clone());
        }
    }
    Value::Object(out)
}

fn valid_image_name(name: &str) -> bool {
    name.len() == 23
        && name.starts_with("im_")
        && name.ends_with(".png")
        && name[3..19]
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

/// Validate a worker output directory: manifest present, well-formed, every listed hash matches,
/// and every referenced image is listed. Returns the problems found.
pub fn verify_worker_output(root: &FsPath) -> Result<(), String> {
    let raw = std::fs::read_to_string(root.join("manifest.json"))
        .map_err(|e| format!("manifest missing: {e}"))?;
    let m: Value = serde_json::from_str(&raw).map_err(|e| format!("manifest malformed: {e}"))?;
    let files = m
        .get("files")
        .and_then(|v| v.as_object())
        .ok_or("manifest malformed: no files object")?;
    for (rel, h) in files {
        if rel.contains("..") || rel.starts_with('/') || rel.contains('\\') {
            return Err(format!("manifest path escapes root: {rel}"));
        }
        let want = h.as_str().ok_or("manifest hash not a string")?;
        let got = sha256_file(&root.join(rel)).map_err(|e| format!("{rel}: {e}"))?;
        if got != want {
            return Err(format!("hash mismatch for {rel}"));
        }
    }
    for t in read_jsonl(&root.join("tasks.jsonl"))? {
        let img = t["image"].as_str().ok_or("task without image")?;
        if !files.contains_key(img) {
            return Err(format!("image {img} not covered by manifest"));
        }
    }
    Ok(())
}

impl Store {
    /// Load one data root (samples layout or dataset layout). Pass `validate=true` for worker output.
    pub fn load_root(&mut self, root: &FsPath, validate: bool) -> Result<Vec<String>, String> {
        if validate {
            verify_worker_output(root)?;
        }
        let mut task_files = vec![root.join("tasks.jsonl")];
        if let Ok(rd) = std::fs::read_dir(root.join("public")) {
            task_files.extend(
                rd.flatten()
                    .map(|e| e.path())
                    .filter(|p| p.extension().is_some_and(|x| x == "jsonl")),
            );
        }
        let mut ids = vec![];
        for f in task_files.into_iter().filter(|f| f.exists()) {
            for t in read_jsonl(&f)? {
                let id = t["task_id"]
                    .as_str()
                    .ok_or("task without task_id")?
                    .to_string();
                let img = t["image"].as_str().ok_or("task without image")?;
                let name = img.rsplit('/').next().unwrap_or("");
                if !valid_image_name(name) {
                    return Err(format!("task {id}: bad image name"));
                }
                let path = root.join(img);
                if !path.is_file()
                    || std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) > MAX_IMAGE_BYTES
                {
                    return Err(format!("task {id}: image missing or too large"));
                }
                self.images.insert(name.to_string(), path);
                self.tasks.insert(id.clone(), project_public(&t));
                ids.push(id);
                if self.tasks.len() > MAX_TASKS {
                    return Err("too many tasks".into());
                }
            }
        }
        for kf in [
            root.join("sample_keys.jsonl"),
            root.join("private").join("answers.jsonl"),
        ] {
            if kf.exists() {
                for k in read_jsonl(&kf)? {
                    if let Some(id) = k["task_id"].as_str() {
                        self.keys.insert(id.to_string(), k.clone());
                    }
                }
            }
        }
        if root.join("pairs.jsonl").exists() {
            self.pairs.extend(read_jsonl(&root.join("pairs.jsonl"))?);
        }
        if root.join("model_attempts.jsonl").exists() {
            for a in read_jsonl(&root.join("model_attempts.jsonl"))? {
                if let Some(id) = a["task_id"].as_str() {
                    self.model_attempts
                        .entry(id.to_string())
                        .or_default()
                        .push(a.clone());
                }
            }
        }
        Ok(ids)
    }
}

pub fn new_state(cfg: Config) -> Result<Shared, String> {
    let mut store = Store::default();
    if cfg.data_dir.exists() {
        store.load_root(&cfg.data_dir, false)?;
    }
    Ok(Arc::new(AppState {
        cfg,
        store: RwLock::new(store),
        jobs: Mutex::new(HashMap::new()),
        gate: Semaphore::new(1),
        counter: AtomicU64::new(0),
    }))
}

pub fn build_app(state: Shared) -> Router {
    let origins: Vec<header::HeaderValue> = state
        .cfg
        .allowed_origins
        .iter()
        .filter_map(|o| o.parse().ok())
        .collect();
    let cors = tower_http::cors::CorsLayer::new()
        .allow_origin(origins)
        .allow_methods([axum::http::Method::GET, axum::http::Method::POST])
        .allow_headers([header::CONTENT_TYPE, "x-panelproof-token".parse().unwrap()]);
    Router::new()
        .route("/health", get(health))
        .route("/v1/capabilities", get(capabilities))
        .route("/v1/tasks", get(list_tasks))
        .route("/v1/tasks/:id", get(get_task))
        .route("/v1/tasks/:id/model-attempts", get(model_attempts))
        .route("/v1/tasks/:id/reveal", post(reveal))
        .route("/v1/images/:name", get(image))
        .route("/v1/arena/pairs", get(arena_pairs))
        .route("/v1/attempts", post(post_attempt))
        .route("/v1/jobs/generate", post(start_job))
        .route("/v1/jobs/:id", get(get_job))
        .layer(DefaultBodyLimit::max(MAX_BODY))
        .layer(cors)
        .with_state(state)
}

async fn health(State(s): State<Shared>) -> Json<Value> {
    let n = s.store.read().await.tasks.len();
    Json(
        json!({ "status": "ok", "service": "pp-api", "version": env!("CARGO_PKG_VERSION"), "tasks_loaded": n }),
    )
}

async fn capabilities(State(s): State<Shared>) -> Json<Value> {
    Json(json!({
        "schema_version": pp_oracle::SCHEMA_VERSION,
        "conditions": ["C0", "C1", "C3"],
        "offline_demo": true,
        "live_models": false,
        "reveal_enabled": s.cfg.reveal_token.is_some(),
        "generation": { "max_count": s.cfg.max_count, "deadline_seconds": s.cfg.job_deadline.as_secs() },
        "limits": { "max_body_bytes": MAX_BODY, "max_tasks": MAX_TASKS },
        "interim": "fixture service; PP-14 owns the production API"
    }))
}

async fn list_tasks(State(s): State<Shared>) -> Json<Value> {
    let st = s.store.read().await;
    Json(Value::Array(st.tasks.values().take(500).cloned().collect()))
}

async fn get_task(State(s): State<Shared>, Path(id): Path<String>) -> ApiResult<Value> {
    let st = s.store.read().await;
    st.tasks
        .get(&id)
        .cloned()
        .map(Json)
        .ok_or_else(|| err(StatusCode::NOT_FOUND, "unknown task"))
}

async fn model_attempts(State(s): State<Shared>, Path(id): Path<String>) -> Json<Value> {
    let st = s.store.read().await;
    let rows: Vec<Value> = st
        .model_attempts
        .get(&id)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .take(3)
        .collect();
    Json(json!({ "task_id": id, "label": "DEMO ONLY", "attempts": rows }))
}

async fn image(State(s): State<Shared>, Path(name): Path<String>) -> Response {
    if !valid_image_name(&name) {
        return err(StatusCode::BAD_REQUEST, "bad image name").into_response();
    }
    let path = { s.store.read().await.images.get(&name).cloned() };
    match path {
        Some(p) => match tokio::fs::read(&p).await {
            Ok(bytes) => (
                [
                    (header::CONTENT_TYPE, "image/png"),
                    (header::CACHE_CONTROL, "public, max-age=3600"),
                ],
                bytes,
            )
                .into_response(),
            Err(_) => err(StatusCode::NOT_FOUND, "image unavailable").into_response(),
        },
        None => err(StatusCode::NOT_FOUND, "unknown image").into_response(),
    }
}

async fn arena_pairs(State(s): State<Shared>) -> Json<Value> {
    // only opaque pair ids and task ids: the variant kind is revealed with the evidence
    let st = s.store.read().await;
    Json(Value::Array(
        st.pairs
            .iter()
            .map(|p| json!({ "pair_id": p["pair_id"], "task_ids": p["task_ids"] }))
            .collect(),
    ))
}

#[derive(Deserialize)]
struct AttemptIn {
    task_id: String,
    response: Value,
}

async fn post_attempt(State(s): State<Shared>, Json(a): Json<AttemptIn>) -> ApiResult<Value> {
    let mut st = s.store.write().await;
    if !st.tasks.contains_key(&a.task_id) {
        return Err(err(StatusCode::NOT_FOUND, "unknown task"));
    }
    let key = st
        .keys
        .get(&a.task_id)
        .ok_or_else(|| err(StatusCode::CONFLICT, "no reference for task"))?;
    let outcome = pp_scoring::score(&key["answer"], &a.response);
    let id = format!("a_{}", s.counter.fetch_add(1, Ordering::SeqCst) + 1);
    let rec = json!({ "attempt_id": id, "task_id": a.task_id, "outcome": outcome.as_str(), "status": "ok", "human": true });
    st.attempts.push(rec.clone());
    Ok(Json(rec))
}

async fn reveal(
    State(s): State<Shared>,
    headers: HeaderMap,
    Path(id): Path<String>,
) -> ApiResult<Value> {
    let want = s
        .cfg
        .reveal_token
        .as_deref()
        .ok_or_else(|| err(StatusCode::FORBIDDEN, "reveal disabled"))?;
    let got = headers
        .get("x-panelproof-token")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if got != want {
        return Err(err(StatusCode::FORBIDDEN, "reveal not authorized"));
    }
    let st = s.store.read().await;
    let key = st
        .keys
        .get(&id)
        .ok_or_else(|| err(StatusCode::NOT_FOUND, "no reference for task"))?;
    Ok(Json(json!({
        "task_id": id,
        "answer": key["answer"],
        "variant_kind": key.get("variant_kind"),
        "skill": key.get("skill"),
        "kind": key.get("kind"),
        "evidence": key.get("evidence"),
        "validation": key.get("validation"),
    })))
}

#[derive(Deserialize)]
struct JobIn {
    seed: String,
    count: u32,
    #[serde(default = "default_difficulty")]
    difficulty: String,
}

fn default_difficulty() -> String {
    "medium".to_string()
}

pub fn valid_seed(seed: &str) -> bool {
    !seed.is_empty()
        && seed.len() <= 40
        && seed
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

async fn start_job(State(s): State<Shared>, Json(j): Json<JobIn>) -> ApiResult<Value> {
    if !valid_seed(&j.seed)
        || j.count == 0
        || j.count > s.cfg.max_count
        || !matches!(j.difficulty.as_str(), "easy" | "medium" | "hard")
    {
        return Err(err(StatusCode::BAD_REQUEST, "invalid seed or count"));
    }
    let key = format!("{}:{}:{}", j.seed, j.count, j.difficulty);
    let id;
    {
        let mut jobs = s.jobs.lock().await;
        if let Some(existing) = jobs.values().find(|x| x.key == key && x.status != "failed") {
            return Ok(Json(job_json(existing, true)));
        }
        id = format!("j_{}", s.counter.fetch_add(1, Ordering::SeqCst) + 1);
        jobs.insert(
            id.clone(),
            Job {
                id: id.clone(),
                key,
                status: "queued",
                started: Instant::now(),
                error: None,
                task_ids: vec![],
            },
        );
    }
    let st = s.clone();
    let (jid, seed, count, difficulty) =
        (id.clone(), j.seed.clone(), j.count, j.difficulty.clone());
    tokio::spawn(async move { run_job(st, jid, seed, count, difficulty).await });
    let jobs = s.jobs.lock().await;
    Ok(Json(job_json(&jobs[&id], false)))
}

async fn run_job(s: Shared, id: String, seed: String, count: u32, difficulty: String) {
    let _permit = s.gate.acquire().await.expect("semaphore open");
    set_job(&s, &id, "running", None, vec![]).await;
    let out = s.cfg.runs_dir.join("jobs").join(&id);
    let mut cmd = tokio::process::Command::new(&s.cfg.python);
    cmd.args(["-m", "panelproof.cli", "factory", "--seed"])
        .arg(&seed)
        .args(["--count"])
        .arg(count.to_string())
        .args(["--out"])
        .arg(&out)
        .args(["--difficulty"])
        .arg(&difficulty)
        .env("PYTHONPATH", s.cfg.repo_root.join("python").join("src"))
        .kill_on_drop(true)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped());
    let res = tokio::time::timeout(s.cfg.job_deadline, async {
        let child = cmd.spawn().map_err(|e| format!("spawn failed: {e}"))?;
        let o = child.wait_with_output().await.map_err(|e| e.to_string())?;
        if o.status.success() {
            Ok(())
        } else {
            let tail = String::from_utf8_lossy(&o.stderr);
            Err(format!(
                "worker exited with {}: {}",
                o.status,
                tail.chars()
                    .rev()
                    .take(300)
                    .collect::<String>()
                    .chars()
                    .rev()
                    .collect::<String>()
            ))
        }
    })
    .await;
    match res {
        Err(_) => set_job(&s, &id, "failed", Some("deadline exceeded".into()), vec![]).await,
        Ok(Err(e)) => set_job(&s, &id, "failed", Some(e), vec![]).await,
        Ok(Ok(())) => {
            let loaded = s.store.write().await.load_root(&out, true);
            match loaded {
                Ok(ids) => set_job(&s, &id, "succeeded", None, ids).await,
                Err(e) => {
                    set_job(
                        &s,
                        &id,
                        "failed",
                        Some(format!("rejected worker output: {e}")),
                        vec![],
                    )
                    .await
                }
            }
        }
    }
}

async fn set_job(
    s: &Shared,
    id: &str,
    status: &'static str,
    error: Option<String>,
    ids: Vec<String>,
) {
    if let Some(j) = s.jobs.lock().await.get_mut(id) {
        j.status = status;
        j.error = error;
        j.task_ids = ids;
    }
}

fn job_json(j: &Job, duplicate: bool) -> Value {
    json!({ "job_id": j.id, "status": j.status, "error": j.error, "task_ids": j.task_ids, "duplicate_of_existing": duplicate })
}

async fn get_job(State(s): State<Shared>, Path(id): Path<String>) -> ApiResult<Value> {
    let mut jobs = s.jobs.lock().await;
    let j = jobs
        .get_mut(&id)
        .ok_or_else(|| err(StatusCode::NOT_FOUND, "unknown job"))?;
    // stale recovery: a job stuck past twice its deadline is failed so it can be re-requested
    if (j.status == "running" || j.status == "queued")
        && j.started.elapsed() > s.cfg.job_deadline * 2 + Duration::from_secs(30)
    {
        j.status = "failed";
        j.error = Some("stale job recovered".into());
    }
    Ok(Json(job_json(j, false)))
}
