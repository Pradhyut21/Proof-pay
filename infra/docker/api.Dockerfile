# Axum API (needs a C compiler for bundled SQLite; the rust image has one).
FROM rust:1-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates crates
COPY migrations migrations
COPY shared shared
RUN cargo build --locked --release -p panelproof-api

FROM debian:bookworm-slim
COPY --from=build /src/target/release/panelproof-api /usr/local/bin/panelproof-api
USER nobody
EXPOSE 3001
ENTRYPOINT ["panelproof-api"]
