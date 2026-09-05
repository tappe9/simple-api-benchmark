FROM rust:1.98.0-bookworm@sha256:82150a52ec202c1b14d7817e14516c392bb7f5cfebd88f1ed531cb37ebd39922 AS build

# The patch release fixes a compiler miscompilation; its official image is not yet published.
RUN rustup toolchain install 1.98.1 --profile minimal --no-self-update
WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY src ./src
RUN cargo +1.98.1 build --release --locked

FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

COPY --from=build /src/target/release/rust-actix /usr/local/bin/rust-actix
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/rust-actix"]
