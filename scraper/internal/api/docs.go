package api

import (
	_ "embed"
	"net/http"
)

//go:embed openapi.yaml
var openAPISpec []byte

func handleOpenAPISpec(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/yaml")
	_, _ = w.Write(openAPISpec)
}

// swaggerUIPage loads swagger-ui-dist from a CDN rather than vendoring it,
// so this stays a single small file instead of pulling in swagger-ui's
// asset bundle. It only needs network access to unpkg.com, not to the API
// itself, which stays reachable offline.
const swaggerUIPage = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>search-engine-scraper API docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>body { margin: 0; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "/openapi.yaml",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis],
      layout: "BaseLayout",
    });
  </script>
</body>
</html>
`

func handleSwaggerUI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write([]byte(swaggerUIPage))
}
