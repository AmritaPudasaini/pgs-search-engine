package storage

import (
	"context"
	"encoding/json"
	"testing"

	kafka "github.com/segmentio/kafka-go"
)

type fakeKafkaWriter struct {
	messages []kafka.Message
}

func (w *fakeKafkaWriter) WriteMessages(_ context.Context, messages ...kafka.Message) error {
	w.messages = append(w.messages, messages...)
	return nil
}

func (w *fakeKafkaWriter) Close() error { return nil }

func TestKafkaSignalEmitterPublishesObjectReference(t *testing.T) {
	writer := &fakeKafkaWriter{}
	emitter := &KafkaSignalEmitter{w: writer}
	signal := CompletionSignal{ObjectKey: "pages/a.json", ObjectSHA256: "abc", PageURL: "https://example.gov.np"}
	if err := emitter.Emit(context.Background(), signal); err != nil {
		t.Fatalf("Emit: %v", err)
	}
	if len(writer.messages) != 1 || string(writer.messages[0].Key) != "abc" {
		t.Fatalf("messages = %+v", writer.messages)
	}
	var decoded CompletionSignal
	if err := json.Unmarshal(writer.messages[0].Value, &decoded); err != nil {
		t.Fatalf("decode signal: %v", err)
	}
	if decoded.ObjectKey != signal.ObjectKey || decoded.CompletedAt.IsZero() {
		t.Fatalf("decoded = %+v", decoded)
	}
}
