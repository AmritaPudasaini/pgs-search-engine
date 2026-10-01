package storage

import (
	"context"
	"fmt"
	"time"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

type pageWriter interface {
	WritePage(context.Context, *model.DFSPayload) (StoredObject, error)
}

type completionEmitter interface {
	Emit(context.Context, CompletionSignal) error
}

// HandoffWriter enforces the DFS-before-Kafka ordering required by ETL.
type HandoffWriter struct {
	dfs     pageWriter
	emitter completionEmitter
	now     func() time.Time
}

func NewHandoffWriter(dfs pageWriter, emitter completionEmitter) (*HandoffWriter, error) {
	if dfs == nil || emitter == nil {
		return nil, fmt.Errorf("DFS writer and completion emitter are required")
	}
	return &HandoffWriter{dfs: dfs, emitter: emitter, now: time.Now}, nil
}

func (w *HandoffWriter) WritePage(ctx context.Context, payload *model.DFSPayload) (StoredObject, error) {
	stored, err := w.dfs.WritePage(ctx, payload)
	if err != nil {
		return StoredObject{}, err
	}
	signal := CompletionSignal{
		Bucket:       stored.Bucket,
		ObjectKey:    stored.Key,
		ObjectSHA256: stored.SHA256,
		PageURL:      payload.StorageMetadata.PageURL,
		TargetDomain: payload.StorageMetadata.TargetDomain,
		ContentType:  payload.StorageMetadata.ContentType,
		ScrapedAt:    payload.StorageMetadata.ScrapedAt,
		CompletedAt:  w.now().UTC(),
	}
	if err := w.emitter.Emit(ctx, signal); err != nil {
		return stored, fmt.Errorf("emit completion signal for %s: %w", stored.Key, err)
	}
	return stored, nil
}
