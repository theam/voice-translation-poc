# Environment Configuration Strategy

## Overview

The production testing framework uses a **Base + Override** configuration strategy for managing multi-environment deployments. This approach enables clean switching between environments (local, dev, staging, prod) without modifying configuration files.

## Configuration Model

### Base Environment (`.env`)

A single base file contains shared defaults across all environments:

- Timeouts and retry behavior
- Logging levels and debug flags
- Feature flags and general settings
- Default values for optional configuration

**Location:** `production/.env`

**Optional:** Yes - all configuration can be provided via environment-specific files or system environment variables

### Environment-Specific Overrides (`.env.{APP_ENV}`)

Each environment has its own dedicated file that overrides base values:

- WebSocket endpoints
- API credentials and authentication
- Environment-dependent timeouts or behavior
- Target system identifiers

**Examples:**
- `.env.local` - Local development
- `.env.dev` - Development server
- `.env.staging` - Staging environment
- `.env.prod` - Production testing

**Optional:** Yes - if no override file exists, only base values (or system env vars) are used

## Environment Selection

The active environment is controlled by the **`APP_ENV`** environment variable:

```bash
# Use local environment
export APP_ENV=local

# Use staging environment
export APP_ENV=staging

# Default is "local" if APP_ENV is not set
```

## Loading Strategy

The configuration system follows these rules strictly:

1. **Load base first:** `.env` is loaded with shared defaults
2. **Determine environment:** Check `APP_ENV` (default: `local`)
3. **Load override:** `.env.{APP_ENV}` is loaded if it exists
4. **Override wins:** Environment-specific values always take precedence
5. **Load once:** Configuration is loaded exactly once at process startup

### Loading Order Example

For `APP_ENV=dev`:

```
1. Load .env (base)
   TRANSLATION_CONNECT_TIMEOUT=10.0
   TRANSLATION_WEBSOCKET_URL=ws://localhost:8000/ws

2. Load .env.dev (override)
   TRANSLATION_WEBSOCKET_URL=wss://dev.example.com/translation

3. Final configuration:
   TRANSLATION_CONNECT_TIMEOUT=10.0 (from base)
   TRANSLATION_WEBSOCKET_URL=wss://dev.example.com/translation (from override)
```

## Usage

### Basic Usage

```python
from production.utils.config import load_config

# Load configuration using Base + Override strategy
# Automatically loads .env, then .env.{APP_ENV}
config = load_config()
```

### Custom Base Path

```python
from pathlib import Path
from production.utils.config import load_config

# Use custom base file location
config = load_config(base_env_path=Path("custom/.env"))
```

### Environment Variables Take Precedence

System environment variables always take precedence over both base and override files (unless `override_existing=True`):

```bash
# This value wins over both .env and .env.dev
export TRANSLATION_WEBSOCKET_URL=wss://custom.example.com/ws

# Run test with custom URL
poetry run prod run-test production/tests/scenarios/test.yaml
```

## File Organization

```
production/
├── .env                    # Base environment (shared defaults)
├── .env.local             # Local development overrides (optional)
├── .env.dev               # Development server overrides (optional)
├── .env.staging           # Staging environment overrides (optional)
├── .env.prod              # Production testing overrides (optional)
└── .env.example           # Example configuration template
```

## Best Practices

### What Goes in `.env` (Base)

✅ **Shared defaults:**
- Default timeouts
- Debug flags
- Logging levels
- Feature flags
- Generic settings that rarely change between environments

❌ **Avoid:**
- Environment-specific URLs
- Credentials or API keys
- Environment-specific behavior

### What Goes in `.env.{APP_ENV}` (Override)

✅ **Environment-specific values:**
- WebSocket URLs
- API endpoints
- Authentication credentials
- Environment-specific timeouts
- Target system identifiers

### Git and Security

```gitignore
# Commit example files only
.env
.env.local
.env.dev
.env.staging
.env.prod

# Keep example template in repo
!.env.example
```

⚠️ **Never commit credentials** - use environment-specific files or CI/CD secrets

## Switching Environments

### Local Development → Dev Server

```bash
# Switch to dev environment
export APP_ENV=dev

# Run tests against dev server
poetry run prod run-test production/tests/scenarios/test.yaml
```

### CI/CD Pipeline

```yaml
# .github/workflows/test.yml
env:
  APP_ENV: staging

jobs:
  test:
    steps:
      - run: poetry run prod run-suite production/tests/scenarios/
```

### Make Targets (Docker)

The framework's Make targets automatically pass `APP_ENV` from your shell to the Docker container:

```bash
# Run tests in dev environment
APP_ENV=dev make test_suite

# Run single test in staging
APP_ENV=staging make test_prod SCENARIO=production/tests/scenarios/test.yaml

# Calibration in prod environment
APP_ENV=prod make calibrate

# Parallel testing in dev
APP_ENV=dev make test_parallel_tests TEST_PATH=production/tests/scenarios/ JOBS=4
```

The `docker-compose.yml` is configured to pass `APP_ENV` through:

```yaml
environment:
  APP_ENV: ${APP_ENV:-local}  # Defaults to "local" if not set
```

### Docker Compose

For persistent environment configuration:

```yaml
# docker-compose.yml or docker-compose.override.yml
services:
  vt-app:
    environment:
      APP_ENV: dev  # Always use dev environment
```

## Configuration Reference

All available configuration options are documented in `production/utils/config.py` in the `FrameworkConfig` dataclass.

## Operational Guarantees

This strategy provides:

✅ **No file editing** - Switch environments by changing `APP_ENV` only
✅ **Deterministic behavior** - Same `APP_ENV` always produces same configuration
✅ **Environment isolation** - No value leakage between environments
✅ **Reproducible tests** - Configuration is explicit and traceable
✅ **CI/CD friendly** - Works seamlessly with environment variables

## Troubleshooting

### Configuration not loading

```bash
# Verify files exist
ls -la production/.env*

# Check current environment
echo $APP_ENV

# Run with debug to see loaded values
TRANSLATION_DEBUG_WIRE=true poetry run prod run-test ...
```

### Override not taking effect

1. Verify `APP_ENV` is set correctly
2. Check file naming: `.env.{APP_ENV}` (e.g., `.env.dev`, not `.env.development`)
3. Ensure override file is in same directory as base `.env`
4. System environment variables always win - check `env | grep TRANSLATION`

### Which file is being used?

The framework loads from the production directory by default. You can verify by adding a unique value to each file and checking which one is active.
