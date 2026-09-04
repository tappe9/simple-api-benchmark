package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

func TestMain(m *testing.M) {
	gin.SetMode(gin.TestMode)
	os.Exit(m.Run())
}

type stubQuerier struct {
	called bool
	query  string
	args   []any
	row    pgx.Row
}

func (stub *stubQuerier) QueryRow(_ context.Context, query string, args ...any) pgx.Row {
	stub.called = true
	stub.query = query
	stub.args = append([]any(nil), args...)
	if stub.row == nil {
		return stubRow{err: errors.New("no row configured")}
	}
	return stub.row
}

type stubRow struct {
	item itemResponse
	err  error
}

func (row stubRow) Scan(destinations ...any) error {
	if row.err != nil {
		return row.err
	}
	if len(destinations) != 3 {
		return fmt.Errorf("expected 3 scan destinations, got %d", len(destinations))
	}

	id, ok := destinations[0].(*int64)
	if !ok {
		return errors.New("first scan destination is not *int64")
	}
	name, ok := destinations[1].(*string)
	if !ok {
		return errors.New("second scan destination is not *string")
	}
	price, ok := destinations[2].(*int)
	if !ok {
		return errors.New("third scan destination is not *int")
	}

	*id = row.item.ID
	*name = row.item.Name
	*price = row.item.Price
	return nil
}

func performRequest(t *testing.T, router http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()

	request := httptest.NewRequest(http.MethodGet, path, nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func decodeJSON[T any](t *testing.T, response *httptest.ResponseRecorder) T {
	t.Helper()

	if got := response.Header().Get("Content-Type"); got != "application/json; charset=utf-8" {
		t.Fatalf("Content-Type = %q, want application/json; charset=utf-8", got)
	}

	var payload T
	decoder := json.NewDecoder(response.Body)
	if err := decoder.Decode(&payload); err != nil {
		t.Fatalf("decode JSON response: %v", err)
	}
	return payload
}

func TestHealthEndpoint(t *testing.T) {
	response := performRequest(t, NewRouter(&stubQuerier{}), "/health")

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if got, want := decodeJSON[healthResponse](t, response), (healthResponse{Status: "ok"}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
}

func TestJSONEndpoint(t *testing.T) {
	response := performRequest(t, NewRouter(&stubQuerier{}), "/json")

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	got := decodeJSON[jsonResponse](t, response)
	want := jsonResponse{Message: "Hello, World!", Items: []int{1, 2, 3, 4, 5}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
}

func TestDatabaseEndpointReturnsTheQueriedItem(t *testing.T) {
	querier := &stubQuerier{
		row: stubRow{item: itemResponse{ID: 42, Name: "Item 42", Price: 4200}},
	}
	response := performRequest(t, NewRouter(querier), "/db/42")

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if got, want := decodeJSON[itemResponse](t, response), (itemResponse{ID: 42, Name: "Item 42", Price: 4200}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
	if !querier.called {
		t.Fatal("database query was not executed")
	}
	if querier.query != "SELECT id, name, price FROM items WHERE id = $1" {
		t.Fatalf("query = %q", querier.query)
	}
	if !reflect.DeepEqual(querier.args, []any{int64(42)}) {
		t.Fatalf("query args = %#v, want []any{int64(42)}", querier.args)
	}
}

func TestDatabaseEndpointReturnsNotFound(t *testing.T) {
	querier := &stubQuerier{row: stubRow{err: pgx.ErrNoRows}}
	response := performRequest(t, NewRouter(querier), "/db/999")

	if response.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusNotFound)
	}
	if got, want := decodeJSON[errorResponse](t, response), (errorResponse{Error: "not found"}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
}

func TestDatabaseEndpointRejectsAnInvalidIDWithoutQuerying(t *testing.T) {
	querier := &stubQuerier{}
	response := performRequest(t, NewRouter(querier), "/db/not-an-integer")

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
	if got, want := decodeJSON[errorResponse](t, response), (errorResponse{Error: "invalid id"}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
	if querier.called {
		t.Fatal("database query executed for an invalid ID")
	}
}

func TestDatabaseEndpointHidesUnexpectedDatabaseErrors(t *testing.T) {
	querier := &stubQuerier{row: stubRow{err: errors.New("database unavailable")}}
	response := performRequest(t, NewRouter(querier), "/db/42")

	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusInternalServerError)
	}
	if got, want := decodeJSON[errorResponse](t, response), (errorResponse{Error: "internal server error"}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
}

func TestCPUEndpointCalculatesFibonacciThirty(t *testing.T) {
	response := performRequest(t, NewRouter(&stubQuerier{}), "/cpu")

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if got, want := decodeJSON[cpuResponse](t, response), (cpuResponse{Input: 30, Result: 832040}); got != want {
		t.Fatalf("response = %#v, want %#v", got, want)
	}
}
