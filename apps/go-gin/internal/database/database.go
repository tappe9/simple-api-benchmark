package database

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	MaxConnections int32 = 10
	connectTimeout       = 5 * time.Second
)

var databaseEnvironmentKeys = []string{
	"DATABASE_HOST",
	"DATABASE_PORT",
	"DATABASE_NAME",
	"DATABASE_USER",
	"DATABASE_PASSWORD",
}

func PoolConfigFromEnvironment() (*pgxpool.Config, error) {
	values := make(map[string]string, len(databaseEnvironmentKeys))
	for _, key := range databaseEnvironmentKeys {
		value := os.Getenv(key)
		if value == "" {
			return nil, fmt.Errorf("required environment variable %s is empty", key)
		}
		values[key] = value
	}

	connectionURL := &url.URL{
		Scheme: "postgres",
		User: url.UserPassword(
			values["DATABASE_USER"],
			values["DATABASE_PASSWORD"],
		),
		Host: net.JoinHostPort(
			values["DATABASE_HOST"],
			values["DATABASE_PORT"],
		),
		Path: "/" + values["DATABASE_NAME"],
	}
	query := connectionURL.Query()
	query.Set("sslmode", "disable")
	connectionURL.RawQuery = query.Encode()

	config, err := pgxpool.ParseConfig(connectionURL.String())
	if err != nil {
		return nil, fmt.Errorf("parse database configuration: %w", err)
	}
	config.MaxConns = MaxConnections
	config.ConnConfig.ConnectTimeout = connectTimeout
	return config, nil
}

func Connect(ctx context.Context) (*pgxpool.Pool, error) {
	config, err := PoolConfigFromEnvironment()
	if err != nil {
		return nil, err
	}

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("create database pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}
	return pool, nil
}
