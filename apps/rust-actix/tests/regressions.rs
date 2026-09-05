use rust_actix::{
    database::{DatabaseConfig, DatabaseConfigError},
    healthcheck::check_health,
};
use std::{
    io::{BufRead, BufReader, Write},
    net::TcpListener,
    thread,
    time::Duration,
};

#[test]
fn database_debug_does_not_expose_password() {
    let config = DatabaseConfig {
        host: "postgres".into(),
        port: 5432,
        database: "benchmark".into(),
        user: "benchmark".into(),
        password: "sensitive-test-password".into(),
    };
    assert!(!format!("{config:?}").contains("sensitive-test-password"));
}

#[test]
fn invalid_port_diagnostics_do_not_echo_untrusted_input() {
    let error = DatabaseConfigError::InvalidPort("sensitive-test-input".into());
    assert!(!error.to_string().contains("sensitive-test-input"));
    assert!(!format!("{error:?}").contains("sensitive-test-input"));
}

#[test]
fn healthcheck_rejects_additional_response_fields() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap().to_string();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut reader = BufReader::new(stream.try_clone().unwrap());
        loop {
            let mut line = String::new();
            if reader.read_line(&mut line).unwrap() == 0 || line == "\r\n" {
                break;
            }
        }
        let body = r#"{"status":"ok","unexpected":true}"#;
        write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).unwrap();
    });
    let result = check_health(&address);
    server.join().unwrap();
    assert!(
        result.is_err(),
        "healthcheck accepted fields outside the readiness contract"
    );
}
