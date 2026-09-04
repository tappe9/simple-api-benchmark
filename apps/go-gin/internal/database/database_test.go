package database

import (
	"strings"
	"testing"
)

func setDatabaseEnvironment(t *testing.T) {
	t.Helper()
	t.Setenv("DATABASE_HOST", "postgres.internal")
	t.Setenv("DATABASE_PORT", "5433")
	t.Setenv("DATABASE_NAME", "benchmark")
	t.Setenv("DATABASE_USER", "benchmark-user")
	t.Setenv("DATABASE_PASSWORD", "local-test-value")
}

func TestPoolConfigFromEnvironment(t *testing.T) {
	setDatabaseEnvironment(t)

	config, err := PoolConfigFromEnvironment()
	if err != nil {
		t.Fatalf("PoolConfigFromEnvironment() error = %v", err)
	}

	if got, want := config.MaxConns, int32(10); got != want {
		t.Fatalf("MaxConns = %d, want %d", got, want)
	}
	if got, want := config.ConnConfig.Host, "postgres.internal"; got != want {
		t.Fatalf("Host = %q, want %q", got, want)
	}
	if got, want := config.ConnConfig.Port, uint16(5433); got != want {
		t.Fatalf("Port = %d, want %d", got, want)
	}
	if got, want := config.ConnConfig.Database, "benchmark"; got != want {
		t.Fatalf("Database = %q, want %q", got, want)
	}
	if got, want := config.ConnConfig.User, "benchmark-user"; got != want {
		t.Fatalf("User = %q, want %q", got, want)
	}
	if got, want := config.ConnConfig.Password, "local-test-value"; got != want {
		t.Fatalf("Password = %q, want %q", got, want)
	}
	if config.ConnConfig.TLSConfig != nil {
		t.Fatal("TLSConfig is non-nil, want local sslmode=disable")
	}
}

func TestPoolConfigFromEnvironmentRequiresEverySetting(t *testing.T) {
	setDatabaseEnvironment(t)
	t.Setenv("DATABASE_HOST", "")

	_, err := PoolConfigFromEnvironment()
	if err == nil {
		t.Fatal("PoolConfigFromEnvironment() error = nil, want missing setting error")
	}
	if !strings.Contains(err.Error(), "DATABASE_HOST") {
		t.Fatalf("error = %q, want DATABASE_HOST", err)
	}
}
