use pp_api::{build_app, new_state, Config};
use std::{net::SocketAddr, path::PathBuf, time::Duration};

fn env(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

#[tokio::main]
async fn main() {
    let repo_root = PathBuf::from(env("PP_REPO_ROOT", "."));
    let cfg = Config {
        data_dir: PathBuf::from(env("PP_DATA_DIR", "data/samples")),
        runs_dir: PathBuf::from(env("PP_RUNS_DIR", "data/runs")),
        repo_root,
        python: env("PP_PYTHON", "python"),
        reveal_token: std::env::var("PP_REVEAL_TOKEN")
            .ok()
            .filter(|t| !t.is_empty()),
        allowed_origins: env(
            "PP_ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        .split(',')
        .map(|s| s.trim().to_string())
        .collect(),
        job_deadline: Duration::from_secs(
            env("PP_JOB_DEADLINE_SECS", "120").parse().unwrap_or(120),
        ),
        max_count: env("PP_MAX_GENERATE_COUNT", "4").parse().unwrap_or(4),
    };
    let bind: SocketAddr = env("PP_BIND", "127.0.0.1:8787")
        .parse()
        .expect("PP_BIND is host:port");
    if !bind.ip().is_loopback() && env("PP_ALLOW_REMOTE", "0") != "1" {
        eprintln!("refusing to bind non-loopback {bind}; set PP_ALLOW_REMOTE=1 to override");
        std::process::exit(2);
    }
    let state = match new_state(cfg) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("failed to load data: {e}");
            std::process::exit(1);
        }
    };
    let listener = tokio::net::TcpListener::bind(bind).await.expect("bind");
    println!("pp-api listening on http://{bind}");
    axum::serve(listener, build_app(state))
        .await
        .expect("serve");
}
