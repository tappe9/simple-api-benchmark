package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"mime"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/tappe9/simple-api-benchmark/apps/go-gin/internal/api"
	"github.com/tappe9/simple-api-benchmark/apps/go-gin/internal/database"
)

const (
	listenAddress      = ":8080"
	healthcheckURL     = "http://127.0.0.1:8080/health"
	healthcheckTimeout = 2 * time.Second
	shutdownTimeout    = 5 * time.Second
)

type healthResponse struct {
	Status string `json:"status"`
}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		ctx, cancel := context.WithTimeout(context.Background(), healthcheckTimeout)
		defer cancel()
		if err := checkHealth(ctx, healthcheckURL); err != nil {
			log.Printf("healthcheck failed: %v", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) != 1 {
		log.Printf("unknown command: %q", os.Args[1:])
		os.Exit(2)
	}

	if err := runServer(); err != nil {
		log.Printf("server failed: %v", err)
		os.Exit(1)
	}
}

func runServer() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	pool, err := database.Connect(ctx)
	if err != nil {
		return err
	}
	defer pool.Close()

	server := &http.Server{
		Addr:              listenAddress,
		Handler:           api.NewRouter(pool),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	serverError := make(chan error, 1)
	go func() {
		serverError <- server.ListenAndServe()
	}()

	select {
	case err := <-serverError:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return fmt.Errorf("listen on %s: %w", listenAddress, err)
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shut down server: %w", err)
	}
	return nil
}

func checkHealth(ctx context.Context, endpoint string) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return fmt.Errorf("create health request: %w", err)
	}

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return fmt.Errorf("request health endpoint: %w", err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected health status: %d", response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return fmt.Errorf("unexpected health content type: %q", response.Header.Get("Content-Type"))
	}

	var payload healthResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		return fmt.Errorf("decode health response: %w", err)
	}
	if payload.Status != "ok" {
		return fmt.Errorf("unexpected health response: status %q", payload.Status)
	}
	return nil
}
