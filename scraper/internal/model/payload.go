package model

import "time"

// DFSPayload is the self-contained page object consumed by downstream ETL.
type DFSPayload struct {
	StorageMetadata   StorageMetadata   `json:"storage_metadata"`
	ExtractedMetadata ExtractedMetadata `json:"extracted_metadata"`
	RawPayload        RawPayload        `json:"raw_payload"`
}

type StorageMetadata struct {
	WebsiteName  string    `json:"website_name"`
	TargetDomain string    `json:"target_domain"`
	PageURL      string    `json:"page_url"`
	ScrapedAt    time.Time `json:"scraped_at"`
	ContentType  string    `json:"content_type"`
	HTTPStatus   int       `json:"http_status"`
	CrawlDepth   int       `json:"crawl_depth"`
}

type ExtractedMetadata struct {
	Title                   string            `json:"title"`
	Description             string            `json:"description"`
	Keywords                []string          `json:"keywords"`
	CanonicalURL            string            `json:"canonical_url,omitempty"`
	OpenGraph               map[string]string `json:"open_graph,omitempty"`
	ContactInfo             ContactInfo       `json:"contact_info"`
	SocialLinks             []string          `json:"social_links"`
	DiscoveredInternalLinks []string          `json:"discovered_internal_links"`
	DiscoveredExternalLinks []string          `json:"discovered_external_links"`
	ImageLinks              []string          `json:"image_links,omitempty"`
	VideoLinks              []string          `json:"video_links,omitempty"`
	MainText                string            `json:"main_text"`
}

type RawPayload struct {
	FileExtension   string `json:"file_extension"`
	ContentEncoding string `json:"content_encoding"`
	Data            string `json:"data"`
}

// StoredDocument describes a binary object saved below the documents path.
type StoredDocument struct {
	SourcePageURL string    `json:"source_page_url"`
	DocumentURL   string    `json:"document_url"`
	StoragePath   string    `json:"storage_path"`
	ContentType   string    `json:"content_type"`
	SHA256        string    `json:"sha256"`
	Size          int64     `json:"size"`
	StoredAt      time.Time `json:"stored_at"`
}
