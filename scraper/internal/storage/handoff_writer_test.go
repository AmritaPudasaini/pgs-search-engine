package storage

import (
	"context"
	"errors"
	"testing"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

type fakePageWriter struct {
	events *[]string
	err    error
}

func (w fakePageWriter) WritePage(context.Context, *model.DFSPayload) (StoredObject, error) {
	*w.events = append(*w.events, "dfs")
	if w.err != nil {
		return StoredObject{}, w.err
	}
	return StoredObject{Bucket: "crawler", Key: "pages/a.json", SHA256: "abc", Size: 10}, nil
}

type fakeEmitter struct {
	events  *[]string
	signals []CompletionSignal
}

func (e *fakeEmitter) Emit(_ context.Context, signal CompletionSignal) error {
	*e.events = append(*e.events, "kafka")
	e.signals = append(e.signals, signal)
	return nil
}

func TestHandoffWriterWritesDFSBeforeKafka(t *testing.T) {
	events := []string{}
	emitter := &fakeEmitter{events: &events}
	w, _ := NewHandoffWriter(fakePageWriter{events: &events}, emitter)
	payload := &model.DFSPayload{StorageMetadata: model.StorageMetadata{PageURL: "https://example.gov.np"}}
	if _, err := w.WritePage(context.Background(), payload); err != nil {
		t.Fatalf("WritePage: %v", err)
	}
	if len(events) != 2 || events[0] != "dfs" || events[1] != "kafka" {
		t.Fatalf("events = %v, want [dfs kafka]", events)
	}
}

func TestHandoffWriterDoesNotSignalAfterDFSFailure(t *testing.T) {
	events := []string{}
	emitter := &fakeEmitter{events: &events}
	w, _ := NewHandoffWriter(fakePageWriter{events: &events, err: errors.New("DFS unavailable")}, emitter)
	if _, err := w.WritePage(context.Background(), &model.DFSPayload{}); err == nil {
		t.Fatal("WritePage error = nil")
	}
	if len(events) != 1 || events[0] != "dfs" || len(emitter.signals) != 0 {
		t.Fatalf("events=%v signals=%v", events, emitter.signals)
	}
}
