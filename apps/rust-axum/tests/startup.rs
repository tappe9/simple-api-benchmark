use std::{
    process::{Command, Output, Stdio},
    thread,
    time::{Duration, Instant},
};

fn invoke(arguments: &[&str], settings: &[(&str, &str)]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_rust-axum"))
        .args(arguments)
        .env_clear()
        .envs(settings.iter().copied())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("start binary");
    let deadline = Instant::now() + Duration::from_secs(12);
    loop {
        if child.try_wait().expect("poll binary").is_some() {
            return child.wait_with_output().expect("read binary output");
        }
        if Instant::now() >= deadline {
            child.kill().expect("kill timed-out binary");
            let output = child.wait_with_output().expect("reap binary");
            panic!("startup exceeded deadline: {output:?}");
        }
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn missing_database_configuration_prevents_startup() {
    let result = invoke(&[], &[]);
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("DATABASE_HOST"));
}

#[test]
fn invalid_cli_is_rejected_before_database_startup() {
    for arguments in [vec!["unknown"], vec!["healthcheck", "unexpected"]] {
        let result = invoke(&arguments, &[]);
        assert!(!result.status.success());
        assert!(String::from_utf8_lossy(&result.stderr).contains("usage: rust-axum"));
    }
}

#[test]
fn unreachable_database_fails_without_leaking_credentials() {
    let result = invoke(&[], &[
        ("DATABASE_HOST", "127.0.0.1"),
        ("DATABASE_PORT", "1"),
        ("DATABASE_NAME", "private-test-database"),
        ("DATABASE_USER", "private-test-user"),
        ("DATABASE_PASSWORD", "private-test-password"),
    ]);
    assert!(!result.status.success());
    let error = String::from_utf8_lossy(&result.stderr);
    assert!(error.contains("database connection failed"));
    assert!(!error.contains("private-test"));
}
