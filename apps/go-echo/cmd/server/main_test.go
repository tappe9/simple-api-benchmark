package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCheckHealthAcceptsTheContractResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write([]byte(`{"status":"ok"}`))
	}))
	defer server.Close()

	if err := checkHealth(context.Background(), server.URL); err != nil {
		t.Fatalf("checkHealth() error = %v", err)
	}
}

func TestCheckHealthRejectsAnUnexpectedPayload(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write([]byte(`{"status":"starting"}`))
	}))
	defer server.Close()

	err := checkHealth(context.Background(), server.URL)
	if err == nil {
		t.Fatal("checkHealth() error = nil, want unexpected payload error")
	}
	if !strings.Contains(err.Error(), "unexpected health response") {
		t.Fatalf("error = %q", err)
	}
}
