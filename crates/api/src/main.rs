use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::{ensure, Context, Result};

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let help = "usage: panelproof-api <dataset-dir> <sqlite-path> [loopback-address:port]";
    let dataset = PathBuf::from(args.next().context(help)?);
    let database = PathBuf::from(args.next().context(help)?);
    let address: SocketAddr = match args.next() {
        Some(address) => address.to_str().context(help)?.parse().context(help)?,
        None => "127.0.0.1:3001".parse()?,
    };
    ensure!(
        args.next().is_none() && address.ip().is_loopback(),
        "{help}"
    );
    let reveal_token = match std::env::var("PANELPROOF_REVEAL_TOKEN") {
        Ok(token) => Some(token),
        Err(std::env::VarError::NotPresent) => None,
        Err(error) => return Err(error.into()),
    };
    let service = panelproof_api::open(&dataset, &database, reveal_token).await?;
    let listener = tokio::net::TcpListener::bind(address).await?;
    eprintln!(
        "PanelProof local API listening on {}",
        listener.local_addr()?
    );
    axum::serve(listener, service)
        .with_graceful_shutdown(async {
            if let Err(error) = tokio::signal::ctrl_c().await {
                eprintln!("cannot register Ctrl+C handler: {error}");
                std::future::pending::<()>().await;
            }
        })
        .await?;
    Ok(())
}
