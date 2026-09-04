FROM rust:1.98.1-bookworm AS build

WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim

COPY --from=build /src/target/release/rust-actix /usr/local/bin/rust-actix
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/rust-actix"]
