package api

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"github.com/labstack/echo/v5"
)

const (
	selectItemQuery = "SELECT id, name, price FROM items WHERE id = $1"
	fibonacciInput  = 30
)

type RowQuerier interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

type healthResponse struct {
	Status string `json:"status"`
}

type jsonResponse struct {
	Message string `json:"message"`
	Items   []int  `json:"items"`
}

type itemResponse struct {
	ID    int64  `json:"id"`
	Name  string `json:"name"`
	Price int    `json:"price"`
}

type errorResponse struct {
	Error string `json:"error"`
}

type cpuResponse struct {
	Input  int `json:"input"`
	Result int `json:"result"`
}

func NewRouter(database RowQuerier) *echo.Echo {
	router := echo.New()

	router.GET("/health", func(c *echo.Context) error {
		return c.JSON(http.StatusOK, healthResponse{Status: "ok"})
	})

	router.GET("/json", func(c *echo.Context) error {
		return c.JSON(http.StatusOK, jsonResponse{
			Message: "Hello, World!",
			Items:   []int{1, 2, 3, 4, 5},
		})
	})

	router.GET("/db/:id", func(c *echo.Context) error {
		id, err := echo.PathParam[int64](c, "id")
		if err != nil {
			return c.JSON(http.StatusBadRequest, errorResponse{Error: "invalid id"})
		}

		var item itemResponse
		err = database.QueryRow(c.Request().Context(), selectItemQuery, id).Scan(
			&item.ID,
			&item.Name,
			&item.Price,
		)
		if errors.Is(err, pgx.ErrNoRows) {
			return c.JSON(http.StatusNotFound, errorResponse{Error: "not found"})
		}
		if err != nil {
			return c.JSON(
				http.StatusInternalServerError,
				errorResponse{Error: "internal server error"},
			)
		}
		return c.JSON(http.StatusOK, item)
	})

	router.GET("/cpu", func(c *echo.Context) error {
		return c.JSON(http.StatusOK, cpuResponse{
			Input:  fibonacciInput,
			Result: fibonacci(fibonacciInput),
		})
	})

	return router
}

func fibonacci(n int) int {
	if n < 2 {
		return n
	}
	return fibonacci(n-1) + fibonacci(n-2)
}
