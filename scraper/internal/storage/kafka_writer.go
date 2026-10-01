package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	kafka "github.com/segmentio/kafka-go"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

// KafkaWriter publishes each crawled Document as a JSON message to a Kafka
// topic -- the hand-off point to the ETL team's pipeline, so they consume
// crawled pages as a stream instead of polling the documents table or an
// NDJSON file. Safe for concurrent use: kafka-go's Writer already
// serializes/batches writes internally.
type KafkaWriter struct {
	w *kafka.Writer
}

// CompletionSignal tells ETL which DFS object is ready. Page bytes stay in
// MinIO; Kafka carries only this small durable handoff event.
type CompletionSignal struct {
	Bucket       string    `json:"bucket"`
	ObjectKey    string    `json:"object_key"`
	ObjectSHA256 string    `json:"object_sha256"`
	PageURL      string    `json:"page_url"`
	TargetDomain string    `json:"target_domain"`
	ContentType  string    `json:"content_type"`
	ScrapedAt    time.Time `json:"scraped_at"`
	CompletedAt  time.Time `json:"completed_at"`
}

type kafkaMessageWriter interface {
	WriteMessages(context.Context, ...kafka.Message) error
	Close() error
}

type KafkaSignalEmitter struct {
	w kafkaMessageWriter
}

func NewKafkaSignalEmitter(brokers []string, topic string) (*KafkaSignalEmitter, error) {
	if len(brokers) == 0 {
		return nil, fmt.Errorf("kafka: at least one broker address is required")
	}
	if topic == "" {
		return nil, fmt.Errorf("kafka: topic is required")
	}
	return &KafkaSignalEmitter{w: &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Topic:        topic,
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireOne,
		BatchTimeout: 100 * time.Millisecond,
		Async:        false,
	}}, nil
}

func (e *KafkaSignalEmitter) Emit(ctx context.Context, signal CompletionSignal) error {
	if signal.ObjectKey == "" || signal.ObjectSHA256 == "" {
		return fmt.Errorf("completion signal requires object key and SHA-256")
	}
	if signal.CompletedAt.IsZero() {
		signal.CompletedAt = time.Now().UTC()
	}
	data, err := json.Marshal(signal)
	if err != nil {
		return fmt.Errorf("marshal completion signal: %w", err)
	}
	if err := e.w.WriteMessages(ctx, kafka.Message{Key: []byte(signal.ObjectSHA256), Value: data}); err != nil {
		return fmt.Errorf("publish DFS completion signal: %w", err)
	}
	return nil
}

func (e *KafkaSignalEmitter) Close() error {
	return e.w.Close()
}

// NewKafkaWriter returns a Writer that publishes to topic on the given
// brokers (comma-separated host:port list). Messages are keyed by
// NormalizedURL so Kafka's own partitioning keeps every version of the same
// page in the same partition -- a downstream consumer that processes
// partitions in order sees a page's updates in fetch order, and consumers
// doing per-partition dedupe/compaction group correctly by page identity
// instead of arrival order.
func NewKafkaWriter(brokers []string, topic string) (*KafkaWriter, error) {
	if len(brokers) == 0 {
		return nil, fmt.Errorf("kafka: at least one broker address is required")
	}
	if topic == "" {
		return nil, fmt.Errorf("kafka: topic is required")
	}
	w := &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Topic:        topic,
		Balancer:     &kafka.Hash{}, // key-based partitioning, see doc comment above
		RequiredAcks: kafka.RequireOne,
		BatchTimeout: 100 * time.Millisecond,
		Async:        false, // Write blocks until the broker acks, so a crawl activity's retry policy sees real delivery failures instead of silently dropping messages
	}
	return &KafkaWriter{w: w}, nil
}

// Write publishes doc as one JSON message, keyed by its NormalizedURL (see
// NewKafkaWriter).
func (kw *KafkaWriter) Write(doc *model.Document) error {
	data, err := json.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal document for kafka: %w", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := kw.w.WriteMessages(ctx, kafka.Message{
		Key:   []byte(doc.NormalizedURL),
		Value: data,
	}); err != nil {
		return fmt.Errorf("publish document %s to kafka: %w", doc.URL, err)
	}
	return nil
}

// Close flushes any buffered messages and closes the underlying connections.
func (kw *KafkaWriter) Close() error {
	return kw.w.Close()
}

// ParseBrokers splits a comma-separated broker list (e.g.
// "kafka-1:9092,kafka-2:9092") into individual addresses, trimming
// whitespace and dropping empty entries.
func ParseBrokers(raw string) []string {
	var out []string
	for _, b := range strings.Split(raw, ",") {
		b = strings.TrimSpace(b)
		if b != "" {
			out = append(out, b)
		}
	}
	return out
}
