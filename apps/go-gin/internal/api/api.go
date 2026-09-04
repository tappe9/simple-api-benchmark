package api

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
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

type cpuResponse struct {
	Input  int `json:"input"`
	Result int `json:"result"`
}

type errorResponse struct {
	Error string `json:"error"`
}

func NewRouter(database RowQuerier) *gin.Engine {
	router := gin.New()
	router.Use(gin.Recovery())

	router.GET("/health", func(ctx *gin.Context) {
		ctx.JSON(http.StatusOK, healthResponse{Status: "ok"})
	})

	router.GET("/json", func(ctx *gin.Context) {
		ctx.JSON(http.StatusOK, jsonResponse{
			Message: "Hello, World!",
			Items:   []int{1, 2, 3, 4, 5},
		})
	})

	router.GET("/db/:id", func(ctx *gin.Context) {
		id, err := strconv.ParseInt(ctx.Param("id"), 10, 64)
		if err != nil {
			ctx.JSON(http.StatusBadRequest, errorResponse{Error: "invalid id"})
			return
		}

		var item itemResponse
		err = database.QueryRow(ctx.Request.Context(), selectItemQuery, id).Scan(
			&item.ID,
			&item.Name,
			&item.Price,
		)
		if errors.Is(err, pgx.ErrNoRows) {
			ctx.JSON(http.StatusNotFound, errorResponse{Error: "not found"})
			return
		}
		if err != nil {
			ctx.JSON(http.StatusInternalServerError, errorResponse{Error: "internal server error"})
			return
		}

		ctx.JSON(http.StatusOK, item)
	})

	router.GET("/cpu", func(ctx *gin.Context) {
		ctx.JSON(http.StatusOK, cpuResponse{
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
