package storage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

// ObjectStore is the narrow MinIO/S3 operation required by Person 3 storage.
type ObjectStore interface {
	PutObject(ctx context.Context, bucket, key string, body io.Reader, size int64, contentType string) error
}

// MinIOObjectStore adapts the official MinIO client to ObjectStore.
type MinIOObjectStore struct {
	client *minio.Client
}

func NewMinIOObjectStore(endpoint, accessKey, secretKey string, secure bool) (*MinIOObjectStore, error) {
	if endpoint == "" {
		return nil, fmt.Errorf("minio endpoint is required")
	}
	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: secure,
	})
	if err != nil {
		return nil, fmt.Errorf("create minio client: %w", err)
	}
	return &MinIOObjectStore{client: client}, nil
}

func (m *MinIOObjectStore) PutObject(ctx context.Context, bucket, key string, body io.Reader, size int64, contentType string) error {
	_, err := m.client.PutObject(ctx, bucket, key, body, size, minio.PutObjectOptions{ContentType: contentType})
	return err
}

type StoredObject struct {
	Bucket string `json:"bucket"`
	Key    string `json:"key"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// MinIOWriter writes one self-contained JSON payload per crawled page.
type MinIOWriter struct {
	store  ObjectStore
	bucket string
	prefix string
}

func NewMinIOWriter(store ObjectStore, bucket, prefix string) (*MinIOWriter, error) {
	if store == nil {
		return nil, fmt.Errorf("object store is required")
	}
	if strings.TrimSpace(bucket) == "" {
		return nil, fmt.Errorf("minio bucket is required")
	}
	return &MinIOWriter{store: store, bucket: bucket, prefix: strings.Trim(prefix, "/")}, nil
}

// BuildDFSPayload maps existing scraper output to README section 3.1.
func BuildDFSPayload(doc *model.Document, raw []byte, websiteName string) (*model.DFSPayload, error) {
	if doc == nil {
		return nil, fmt.Errorf("document is required")
	}
	u, err := url.Parse(doc.URL)
	if err != nil || u.Hostname() == "" {
		return nil, fmt.Errorf("invalid document URL %q", doc.URL)
	}
	targetDomain := doc.Host
	if targetDomain == "" {
		targetDomain = u.Hostname()
	}
	scrapedAt := doc.FetchedAt
	if scrapedAt.IsZero() {
		scrapedAt = time.Now().UTC()
	}
	return &model.DFSPayload{
		StorageMetadata: model.StorageMetadata{
			WebsiteName:  websiteName,
			TargetDomain: targetDomain,
			PageURL:      doc.URL,
			ScrapedAt:    scrapedAt,
			ContentType:  doc.ContentType,
			HTTPStatus:   doc.StatusCode,
			CrawlDepth:   doc.Depth,
		},
		ExtractedMetadata: model.ExtractedMetadata{
			Title:                   doc.Title,
			Description:             doc.MetaDescription,
			Keywords:                doc.MetaKeywords,
			CanonicalURL:            doc.CanonicalURL,
			OpenGraph:               doc.OpenGraph,
			ContactInfo:             doc.ContactInfo,
			SocialLinks:             doc.SocialLinks,
			DiscoveredInternalLinks: doc.InternalLinks,
			DiscoveredExternalLinks: doc.ExternalLinks,
			ImageLinks:              doc.ImageLinks,
			VideoLinks:              doc.VideoLinks,
			MainText:                doc.Text,
		},
		RawPayload: model.RawPayload{
			FileExtension:   payloadExtension(doc.ContentType, u.Path),
			ContentEncoding: "base64",
			Data:            base64.StdEncoding.EncodeToString(raw),
		},
	}, nil
}

func (w *MinIOWriter) WritePage(ctx context.Context, payload *model.DFSPayload) (StoredObject, error) {
	if payload == nil {
		return StoredObject{}, fmt.Errorf("DFS payload is required")
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return StoredObject{}, fmt.Errorf("marshal DFS payload: %w", err)
	}
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	domain := safePathPart(payload.StorageMetadata.TargetDomain)
	date := payload.StorageMetadata.ScrapedAt.UTC().Format("2006/01/02")
	key := path.Join(w.prefix, "pages", domain, date, digest+".json")
	if err := w.store.PutObject(ctx, w.bucket, key, bytes.NewReader(data), int64(len(data)), "application/json"); err != nil {
		return StoredObject{}, fmt.Errorf("write DFS object %s: %w", key, err)
	}
	return StoredObject{Bucket: w.bucket, Key: key, SHA256: digest, Size: int64(len(data))}, nil
}

func payloadExtension(contentType, rawPath string) string {
	if extensions, _ := mime.ExtensionsByType(strings.Split(contentType, ";")[0]); len(extensions) > 0 {
		return strings.TrimPrefix(extensions[0], ".")
	}
	if ext := strings.TrimPrefix(path.Ext(rawPath), "."); ext != "" {
		return strings.ToLower(ext)
	}
	return "html"
}

func safePathPart(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = strings.ReplaceAll(value, "/", "-")
	value = strings.ReplaceAll(value, "\\", "-")
	if value == "" || value == "." || value == ".." {
		return "unknown"
	}
	return value
}
