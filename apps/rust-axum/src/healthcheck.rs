use serde::Deserialize;
use std::{
    error::Error,
    fmt,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    time::Duration,
};

const HEALTHCHECK_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Debug)]
pub struct HealthcheckError(String);

impl HealthcheckError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for HealthcheckError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for HealthcheckError {}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HealthResponse {
    status: String,
}

pub fn check_health(address: &str) -> Result<(), HealthcheckError> {
    let socket = address
        .parse::<SocketAddr>()
        .map_err(|error| HealthcheckError::new(format!("invalid health address: {error}")))?;
    let mut stream = TcpStream::connect_timeout(&socket, HEALTHCHECK_TIMEOUT)
        .map_err(|error| HealthcheckError::new(format!("connect to health endpoint: {error}")))?;
    stream
        .set_read_timeout(Some(HEALTHCHECK_TIMEOUT))
        .map_err(|error| HealthcheckError::new(format!("set health read timeout: {error}")))?;
    stream
        .set_write_timeout(Some(HEALTHCHECK_TIMEOUT))
        .map_err(|error| HealthcheckError::new(format!("set health write timeout: {error}")))?;

    let request = format!("GET /health HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n");
    stream
        .write_all(request.as_bytes())
        .map_err(|error| HealthcheckError::new(format!("write health request: {error}")))?;

    let mut response = Vec::new();
    stream
        .read_to_end(&mut response)
        .map_err(|error| HealthcheckError::new(format!("read health response: {error}")))?;
    validate_response(&response)
}

fn validate_response(response: &[u8]) -> Result<(), HealthcheckError> {
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| HealthcheckError::new("health response has no header separator"))?;
    let headers = std::str::from_utf8(&response[..separator])
        .map_err(|error| HealthcheckError::new(format!("health headers are not UTF-8: {error}")))?;
    let body = &response[separator + 4..];

    let mut lines = headers.split("\r\n");
    let status_line = lines
        .next()
        .ok_or_else(|| HealthcheckError::new("health response has no status line"))?;
    if !status_line.starts_with("HTTP/1.1 200 ") {
        return Err(HealthcheckError::new(format!(
            "unexpected health status line: {status_line:?}"
        )));
    }

    let is_json = lines.any(|line| {
        line.split_once(':').is_some_and(|(name, value)| {
            name.eq_ignore_ascii_case("content-type")
                && value
                    .trim()
                    .to_ascii_lowercase()
                    .starts_with("application/json")
        })
    });
    if !is_json {
        return Err(HealthcheckError::new(
            "health response Content-Type is not application/json",
        ));
    }

    let payload: HealthResponse = serde_json::from_slice(body)
        .map_err(|error| HealthcheckError::new(format!("decode health response: {error}")))?;
    if payload.status != "ok" {
        return Err(HealthcheckError::new(format!(
            "unexpected health payload status: {:?}",
            payload.status
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::check_health;
    use std::{
        io::{BufRead, BufReader, Write},
        net::TcpListener,
        thread::{self, JoinHandle},
    };

    fn serve(response: &'static str) -> (String, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test health server");
        let address = listener.local_addr().expect("read test server address");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept health request");
            let mut reader = BufReader::new(stream.try_clone().expect("clone test stream"));
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).expect("read request line");
                if line == "\r\n" || line.is_empty() {
                    break;
                }
            }
            stream
                .write_all(response.as_bytes())
                .expect("write health response");
        });
        (address.to_string(), handle)
    }

    #[test]
    fn healthcheck_accepts_the_contract_response() {
        let (address, handle) = serve(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}",
        );

        check_health(&address).expect("contract response should be healthy");
        handle.join().expect("health server should finish");
    }

    #[test]
    fn healthcheck_rejects_an_unhealthy_status() {
        let (address, handle) = serve(
            "HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"no\"}",
        );

        let error = check_health(&address).expect_err("503 response should fail");
        assert!(error.to_string().contains("unexpected health status"));
        handle.join().expect("health server should finish");
    }

    #[test]
    fn healthcheck_rejects_an_unexpected_payload() {
        let (address, handle) = serve(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"no\"}",
        );

        let error = check_health(&address).expect_err("unexpected payload should fail");
        assert!(error.to_string().contains("unexpected health payload"));
        handle.join().expect("health server should finish");
    }
}
