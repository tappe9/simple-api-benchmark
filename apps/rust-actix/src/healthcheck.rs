#[cfg(test)]
mod tests {
    use super::check_health;
    use std::{
        io::{Read, Write},
        net::{SocketAddr, TcpListener},
        thread::{self, JoinHandle},
        time::Duration,
    };

    fn spawn_server(response: &'static [u8]) -> (SocketAddr, JoinHandle<()>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind test server");
        let address = listener.local_addr().expect("read test server address");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept healthcheck request");
            let mut request = [0_u8; 512];
            let length = stream.read(&mut request).expect("read healthcheck request");
            let request = std::str::from_utf8(&request[..length]).expect("request should be UTF-8");
            assert!(request.starts_with("GET /health HTTP/1.1\r\n"));
            stream.write_all(response).expect("write healthcheck response");
        });
        (address, handle)
    }

    #[test]
    fn healthcheck_accepts_the_contract_response() {
        let (address, server) = spawn_server(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}",
        );

        let result = check_health(address, Duration::from_secs(1));
        server.join().expect("test server should finish");

        result.expect("contract response should be healthy");
    }

    #[test]
    fn healthcheck_rejects_a_non_success_status() {
        let (address, server) = spawn_server(
            b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"starting\"}",
        );

        let error = check_health(address, Duration::from_secs(1))
            .expect_err("non-success status should fail");
        server.join().expect("test server should finish");

        assert!(error.to_string().contains("status"));
    }

    #[test]
    fn healthcheck_rejects_a_non_json_content_type() {
        let (address, server) = spawn_server(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nok",
        );

        let error = check_health(address, Duration::from_secs(1))
            .expect_err("non-JSON response should fail");
        server.join().expect("test server should finish");

        assert!(error.to_string().contains("content type"));
    }

    #[test]
    fn healthcheck_rejects_an_unexpected_payload() {
        let (address, server) = spawn_server(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"starting\"}",
        );

        let error = check_health(address, Duration::from_secs(1))
            .expect_err("unexpected payload should fail");
        server.join().expect("test server should finish");

        assert!(error.to_string().contains("payload"));
    }
}
