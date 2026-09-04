FROM golang:1.27.1-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/go-gin ./cmd/server

FROM scratch

COPY --from=build /out/go-gin /go-gin
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/go-gin"]
