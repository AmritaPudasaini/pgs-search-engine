.PHONY: build test proto

build:
	go build ./...

test:
	go test ./...

proto:
	protoc --go_out=. --go-grpc_out=. proto/search_engine.proto
