package storage

import "context"

// RunStats is the same shape as workflows.CrawlStats, duplicated here so
// this package doesn't import internal/workflows (which itself imports
// internal/activities, which imports this package -- importing workflows
// here would be a cycle).
type RunStats struct {
	Fetched      int
	Succeeded    int
	Failed       int
	Skipped      int
	DomainCapped int
}

// StartRunInput is the argument to RunRecorder.StartRun.
type StartRunInput struct {
	SeedCount int
	MaxDepth  int
	MaxPages  int
}

// RunRecorder persists the health/validation summary for one crawl run --
// what other teams check before consuming a batch of documents: was the run
// complete, how many pages succeeded/failed/were skipped, when it ran.
//
// Implementations must be safe for concurrent use (activities may call
// UpdateRunStats from concurrent workflow tasks across worker processes,
// though in practice CrawlWorkflow only calls it from its own single
// logical thread).
type RunRecorder interface {
	// StartRun records a new run and returns its ID. Called once, on the
	// first Continue-As-New segment of a crawl.
	StartRun(ctx context.Context, in StartRunInput) (int64, error)
	// UpdateRunStats records progress on a still-running run -- called
	// after every page and before every Continue-As-New handoff, so a run's
	// status is visible while it's still going.
	UpdateRunStats(ctx context.Context, runID int64, stats RunStats) error
	// FinishRun marks a run terminal (status is "completed" or "failed")
	// with its final stats.
	FinishRun(ctx context.Context, runID int64, status string, stats RunStats, errMsg string) error
}

// NoopRunRecorder is used when no run-tracking backend is configured (e.g.
// --storage=ndjson, which has no database to record into). StartRun always
// returns 0, and callers should skip Update/FinishRun calls when the run ID
// is 0 rather than invoking a Temporal activity that does nothing.
type NoopRunRecorder struct{}

func (NoopRunRecorder) StartRun(context.Context, StartRunInput) (int64, error) { return 0, nil }
func (NoopRunRecorder) UpdateRunStats(context.Context, int64, RunStats) error  { return nil }
func (NoopRunRecorder) FinishRun(context.Context, int64, string, RunStats, string) error {
	return nil
}
