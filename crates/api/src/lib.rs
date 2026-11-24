//! Local HTTP service for importing, inspecting and scoring accepted task bundles.

mod artifacts;

use std::collections::BTreeMap;
use std::path::Path as FilePath;
use std::sync::Arc;

use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use panelproof_scoring::{answers_match, Answer};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};
use sqlx::SqlitePool;
use subtle::ConstantTimeEq;

use artifacts::{load_tasks, valid_answer, valid_id, EvidenceRegion, PublicTask, Task};

#[derive(Clone)]
struct AppState {
    tasks: Arc<BTreeMap<String, Task>>,
    db: SqlitePool,
    reveal_token: Option<Arc<str>>,
}

/// Import a read-only dataset and construct the local routes.
pub async fn open(
    dataset: &FilePath,
    database: &FilePath,
    reveal_token: Option<String>,
) -> anyhow::Result<Router> {
    anyhow::ensure!(
        reveal_token.as_ref().is_none_or(|token| {
            (16..=128).contains(&token.len()) && token.bytes().all(|b| b.is_ascii_graphic())
        }),
        "reveal token must contain 16–128 visible ASCII characters"
    );
    let tasks = Arc::new(load_tasks(dataset)?);
    let db = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(
            SqliteConnectOptions::new()
                .filename(database)
                .create_if_missing(true),
        )
        .await?;
    sqlx::raw_sql(include_str!("../../../migrations/001_init.sql"))
        .execute(&db)
        .await?;
    Ok(Router::new()
        .route("/healthz", get(health))
        .route("/api/v1/capabilities", get(capabilities))
        .route("/api/v1/tasks", get(list_tasks))
        .route("/api/v1/tasks/{id}", get(task))
        .route("/api/v1/tasks/{id}/image", get(image))
        .route("/api/v1/tasks/{id}/reveal", post(reveal))
        .route("/api/v1/attempts", post(attempt))
        .layer(DefaultBodyLimit::max(16 * 1024))
        .with_state(AppState {
            tasks,
            db,
            reveal_token: reveal_token.map(Arc::from),
        }))
}

struct ApiError(StatusCode, &'static str);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({ "error": self.1 }))).into_response()
    }
}

async fn health(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    sqlx::query("SELECT 1")
        .execute(&state.db)
        .await
        .map_err(|_| ApiError(StatusCode::SERVICE_UNAVAILABLE, "database_unavailable"))?;
    Ok(Json(json!({ "status": "ok", "schema_version": "1.0.0" })))
}

async fn capabilities(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "mode": "local_import",
        "schema_version": "1.0.0",
        "human_attempts": state.reveal_token.is_some(),
        "dev_evidence_reveal": state.reveal_token.is_some(),
        "generation_jobs": false,
        "evaluation_jobs": false,
    }))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskQuery {
    cursor: Option<String>,
    limit: Option<usize>,
}

#[derive(Serialize)]
struct TaskPage {
    items: Vec<PublicTask>,
    next_cursor: Option<String>,
}

async fn list_tasks(
    State(state): State<AppState>,
    Query(query): Query<TaskQuery>,
) -> Result<Json<TaskPage>, ApiError> {
    let limit = query.limit.unwrap_or(25);
    if !(1..=100).contains(&limit) || query.cursor.as_deref().is_some_and(|id| !valid_id(id)) {
        return Err(ApiError(StatusCode::BAD_REQUEST, "invalid_pagination"));
    }
    let mut items: Vec<_> = state
        .tasks
        .values()
        .filter(|entry| {
            query
                .cursor
                .as_ref()
                .is_none_or(|cursor| &entry.public.task_id > cursor)
        })
        .take(limit + 1)
        .map(|entry| entry.public.clone())
        .collect();
    let next_cursor = if items.len() > limit {
        items.truncate(limit);
        items.last().map(|entry| entry.task_id.clone())
    } else {
        None
    };
    Ok(Json(TaskPage { items, next_cursor }))
}

fn get_task<'a>(state: &'a AppState, id: &str) -> Result<&'a Task, ApiError> {
    if !valid_id(id) {
        return Err(ApiError(StatusCode::BAD_REQUEST, "invalid_task_id"));
    }
    state
        .tasks
        .get(id)
        .ok_or(ApiError(StatusCode::NOT_FOUND, "task_not_found"))
}

async fn task(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<PublicTask>, ApiError> {
    Ok(Json(get_task(&state, &id)?.public.clone()))
}

async fn image(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    get_task(&state, &id)?;
    let png = tokio::task::spawn_blocking(move || state.tasks[&id].read_image())
        .await
        .ok()
        .and_then(Result::ok)
        .ok_or(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "image_unavailable",
        ))?;
    Ok((
        [
            (header::CONTENT_TYPE, HeaderValue::from_static("image/png")),
            (
                header::X_CONTENT_TYPE_OPTIONS,
                HeaderValue::from_static("nosniff"),
            ),
        ],
        png,
    )
        .into_response())
}

fn authorized_task<'a>(
    state: &'a AppState,
    headers: &HeaderMap,
    id: &str,
) -> Result<&'a Task, ApiError> {
    let task = get_task(state, id)?;
    let token = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let permitted = state
        .reveal_token
        .as_deref()
        .zip(token)
        .is_some_and(|(expected, token)| bool::from(expected.as_bytes().ct_eq(token.as_bytes())));
    if !permitted || !task.supports_demo() {
        return Err(ApiError(StatusCode::FORBIDDEN, "demo_evidence_unavailable"));
    }
    Ok(task)
}

#[derive(Serialize)]
struct Reveal<'a> {
    task_id: &'a str,
    answer: &'a Answer,
    tolerance_milli: Option<i64>,
    evidence_regions: Option<&'a [EvidenceRegion]>,
    solver_version: &'a str,
}

async fn reveal(
    State(state): State<AppState>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let task = authorized_task(&state, &headers, &id)?;
    Ok((
        [(header::CACHE_CONTROL, HeaderValue::from_static("no-store"))],
        Json(Reveal {
            task_id: &id,
            answer: task.answer(),
            tolerance_milli: task.tolerance_milli(),
            evidence_regions: task.evidence(),
            solver_version: task.solver_version(),
        }),
    )
        .into_response())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AttemptInput {
    task_id: String,
    answer: Answer,
}

#[derive(Serialize)]
struct AttemptResult {
    task_id: String,
    correct: bool,
}

const DB_ERROR: ApiError = ApiError(StatusCode::SERVICE_UNAVAILABLE, "database_unavailable");

async fn attempt(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(input): Json<AttemptInput>,
) -> Result<Response, ApiError> {
    let task = authorized_task(&state, &headers, &input.task_id)?;
    let key = headers
        .get("idempotency-key")
        .and_then(|value| value.to_str().ok())
        .filter(|id| valid_id(id))
        .ok_or(ApiError(StatusCode::BAD_REQUEST, "invalid_idempotency_key"))?;
    if !valid_answer(&input.answer) {
        return Err(ApiError(StatusCode::UNPROCESSABLE_ENTITY, "invalid_answer"));
    }
    let correct = answers_match(task.answer(), &input.answer, task.tolerance_milli())
        .map_err(|_| ApiError(StatusCode::UNPROCESSABLE_ENTITY, "invalid_answer"))?;
    let answer = serde_json::to_string(&input.answer)
        .map_err(|_| ApiError(StatusCode::UNPROCESSABLE_ENTITY, "invalid_answer"))?;
    let mut transaction = state.db.begin().await.map_err(|_| DB_ERROR)?;
    let inserted = sqlx::query(
        "INSERT INTO human_attempts (task_fingerprint, task_id, idempotency_key, submitted_answer, correct)
         VALUES (?, ?, ?, ?, ?) ON CONFLICT(task_fingerprint, idempotency_key) DO NOTHING",
    ).bind(&task.fingerprint).bind(&input.task_id).bind(key).bind(&answer).bind(correct)
        .execute(&mut *transaction).await.map_err(|_| DB_ERROR)?.rows_affected() == 1;
    let (stored_answer, stored_correct): (String, bool) = sqlx::query_as(
        "SELECT submitted_answer, correct FROM human_attempts WHERE task_fingerprint = ? AND idempotency_key = ?",
    ).bind(&task.fingerprint).bind(key).fetch_one(&mut *transaction).await.map_err(|_| DB_ERROR)?;
    transaction.commit().await.map_err(|_| DB_ERROR)?;
    if stored_answer != answer {
        return Err(ApiError(StatusCode::CONFLICT, "idempotency_key_reused"));
    }
    let status = if inserted {
        StatusCode::CREATED
    } else {
        StatusCode::OK
    };
    Ok((
        status,
        [(header::CACHE_CONTROL, HeaderValue::from_static("no-store"))],
        Json(AttemptResult {
            task_id: input.task_id,
            correct: stored_correct,
        }),
    )
        .into_response())
}
