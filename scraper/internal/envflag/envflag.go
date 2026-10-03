// Package envflag registers standard library flags whose default value can
// be overridden by an environment variable, so the same binary is
// configurable identically from a shell (`--flag=x`) or from a container
// orchestrator's env vars (Docker Compose `environment:`, Kubernetes
// ConfigMap/Secret `env:`) without a wrapper script or a second config
// system.
//
// The env var name is the flag name upper-cased with dashes turned to
// underscores: --database-url becomes DATABASE_URL. An explicit CLI flag
// always wins over the env var, which wins over the hardcoded default.
package envflag

import (
	"flag"
	"os"
	"strconv"
	"strings"
	"time"
)

func envName(flagName string) string {
	return strings.ToUpper(strings.ReplaceAll(flagName, "-", "_"))
}

// String registers a string flag defaulting to the env var's value (if set
// and non-empty), falling back to def otherwise.
func String(name, def, usage string) *string {
	if v := os.Getenv(envName(name)); v != "" {
		def = v
	}
	return flag.String(name, def, usage)
}

// Int registers an int flag defaulting to the env var's value (if set and
// parseable), falling back to def otherwise.
func Int(name string, def int, usage string) *int {
	if v := os.Getenv(envName(name)); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil {
			def = parsed
		}
	}
	return flag.Int(name, def, usage)
}

// Duration registers a duration flag defaulting to the env var's value (if
// set and parseable), falling back to def otherwise.
func Duration(name string, def time.Duration, usage string) *time.Duration {
	if v := os.Getenv(envName(name)); v != "" {
		if parsed, err := time.ParseDuration(v); err == nil {
			def = parsed
		}
	}
	return flag.Duration(name, def, usage)
}

// Bool registers a bool flag defaulting to the env var's value (if set and
// parseable), falling back to def otherwise.
func Bool(name string, def bool, usage string) *bool {
	if v := os.Getenv(envName(name)); v != "" {
		if parsed, err := strconv.ParseBool(v); err == nil {
			def = parsed
		}
	}
	return flag.Bool(name, def, usage)
}
