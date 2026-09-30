package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	kafka "github.com/segmentio/kafka-go"

	"search-engine-scraper/internal/model"
)

// KafkaWriter publishes each crawled Document as a JSON message to a Kafka
// topic -- the hand-off point to the ETL team's pipeline, so they consume
// crawled pages as a stream instead of polling the documents table or an
// NDJSON file. Safe for concurrent use: kafka-go's Writer already
// serializes/batches writes internally.
type KafkaWriter struct {
	w *kafka.Writer
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
