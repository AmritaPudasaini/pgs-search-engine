package storage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

const DefaultMaxDocumentBytes int64 = 32 << 20

type DocumentDownloader struct {
	client   *http.Client
	store    ObjectStore
	bucket   string
	prefix   string
	maxBytes int64
	now      func() time.Time
}

func NewDocumentDownloader(client *http.Client, store ObjectStore, bucket, prefix string, maxBytes int64) (*DocumentDownloader, error) {
	if client == nil || store == nil {
		return nil, fmt.Errorf("HTTP client and object store are required")
	}
	if bucket == "" {
		return nil, fmt.Errorf("document bucket is required")
	}
	if maxBytes <= 0 {
		maxBytes = DefaultMaxDocumentBytes
	}
	return &DocumentDownloader{client: client, store: store, bucket: bucket, prefix: strings.Trim(prefix, "/"), maxBytes: maxBytes, now: time.Now}, nil
}

func (d *DocumentDownloader) Download(ctx context.Context, sourcePageURL, documentURL string) (*model.StoredDocument, error) {
	u, err := url.Parse(documentURL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" {
		return nil, fmt.Errorf("invalid document URL %q", documentURL)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, documentURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build document request: %w", err)
	}
	req.Header.Set("Accept", strings.Join(allowedDocumentTypes(), ","))
	resp, err := d.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("download document: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("download document: HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > d.maxBytes {
		return nil, fmt.Errorf("document exceeds %d-byte limit", d.maxBytes)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, d.maxBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read document: %w", err)
	}
	if int64(len(data)) > d.maxBytes {
		return nil, fmt.Errorf("document exceeds %d-byte limit", d.maxBytes)
	}
	contentType := strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0])
	if contentType == "" {
		contentType = http.DetectContentType(data)
	}
	if !isAllowedDocumentType(contentType) {
		return nil, fmt.Errorf("unsupported document content type %q", contentType)
	}

	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	filename := safeDocumentName(path.Base(u.Path), contentType)
	key := path.Join(d.prefix, "documents", digest[:2], digest+"-"+filename)
	if err := d.store.PutObject(ctx, d.bucket, key, bytes.NewReader(data), int64(len(data)), contentType); err != nil {
		return nil, fmt.Errorf("store document: %w", err)
	}
	metadata := &model.StoredDocument{
		SourcePageURL: sourcePageURL,
		DocumentURL:   documentURL,
		StoragePath:   "s3://" + d.bucket + "/" + key,
		ContentType:   contentType,
		SHA256:        digest,
		Size:          int64(len(data)),
		StoredAt:      d.now().UTC(),
	}
	metadataData, err := json.Marshal(metadata)
	if err != nil {
		return nil, fmt.Errorf("marshal document metadata: %w", err)
	}
	metadataKey := key + ".metadata.json"
	if err := d.store.PutObject(ctx, d.bucket, metadataKey, bytes.NewReader(metadataData), int64(len(metadataData)), "application/json"); err != nil {
		return nil, fmt.Errorf("store document metadata: %w", err)
	}
	return metadata, nil
}

func allowedDocumentTypes() []string {
	return []string{
		"application/pdf",
		"application/msword",
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"application/vnd.ms-excel",
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"application/vnd.ms-powerpoint",
		"application/vnd.openxmlformats-officedocument.presentationml.presentation",
		"application/rtf",
		"text/plain",
	}
}

func isAllowedDocumentType(contentType string) bool {
	for _, allowed := range allowedDocumentTypes() {
		if contentType == allowed {
			return true
		}
	}
	return false
}

func safeDocumentName(name, contentType string) string {
	name = path.Base(strings.TrimSpace(name))
	if name == "" || name == "." || name == "/" {
		name = "document"
	}
	name = strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '-' || r == '_' {
			return r
		}
		return '-'
	}, name)
	if path.Ext(name) == "" {
		if extensions, _ := mime.ExtensionsByType(contentType); len(extensions) > 0 {
			name += extensions[0]
		}
	}
	return name
}
