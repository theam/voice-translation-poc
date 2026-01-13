# Environment Variable Configuration

The Voice Translation server supports configuration via environment variables using the `VT_` prefix. Environment variables have the **highest priority** and override values from YAML configuration files.

## Configuration Hierarchy

Configuration is merged in the following order (later sources override earlier ones):

1. **Default config** - Built-in defaults (`DEFAULT_CONFIG`)
2. **YAML files** - `.config.yml` and any specified config files
3. **Environment variables** - `VT_*` prefixed variables (highest priority)

## Environment Variable Naming Convention

Environment variables follow this pattern:

```
VT_{PATH_TO_PROPERTY}
```

Where:
- **Prefix**: `VT_` (Voice Translation)
- **Separator**: `_` for nested paths
- **Case**: ALL UPPERCASE
- **Path**: Dot-separated config path converted to underscores

### Examples

| Config Path | Environment Variable | Example Value |
|------------|---------------------|---------------|
| `system.host` | `VT_SYSTEM_HOST` | `127.0.0.1` |
| `system.port` | `VT_SYSTEM_PORT` | `9000` |
| `system.log_level` | `VT_SYSTEM_LOG_LEVEL` | `DEBUG` |
| `system.log_wire` | `VT_SYSTEM_LOG_WIRE` | `true` |
| `system.default_provider` | `VT_SYSTEM_DEFAULT_PROVIDER` | `voicelive` |
| `buffering.ingress_queue_max` | `VT_BUFFERING_INGRESS_QUEUE_MAX` | `5000` |
| `dispatch.batching.enabled` | `VT_DISPATCH_BATCHING_ENABLED` | `false` |
| `providers.openai.api_key` | `VT_PROVIDERS_OPENAI_API_KEY` | `sk-123...` |
| `providers.openai.endpoint` | `VT_PROVIDERS_OPENAI_ENDPOINT` | `https://api.openai.com` |
| `providers.voicelive.settings.model` | `VT_PROVIDERS_VOICELIVE_SETTINGS_MODEL` | `gpt-4` |

## Type Conversion

Environment variables are strings, but they are automatically converted to the appropriate type based on the existing configuration value:

### Boolean Values

Accepts multiple formats (case-insensitive):

**True values**: `true`, `yes`, `1`, `on`
**False values**: `false`, `no`, `0`, `off`

```bash
VT_SYSTEM_LOG_WIRE=true
VT_DISPATCH_BATCHING_ENABLED=false
```

### Integer Values

```bash
VT_BUFFERING_INGRESS_QUEUE_MAX=5000
VT_DISPATCH_BATCHING_MAX_BATCH_MS=300
```

### Float Values

```bash
VT_PROVIDERS_VOICELIVE_SETTINGS_SESSION_OPTIONS_TEMPERATURE=0.8
```

### String Values

```bash
VT_SYSTEM_LOG_LEVEL=DEBUG
VT_PROVIDERS_OPENAI_API_KEY=sk-proj-abc123
VT_DISPATCH_DEFAULT_PROVIDER=voicelive
```

### Null/None Values

To unset a value, use empty string or special keywords:

```bash
VT_PROVIDERS_OPENAI_ENDPOINT=          # Empty string → None
VT_PROVIDERS_OPENAI_ENDPOINT=null      # → None
VT_PROVIDERS_OPENAI_ENDPOINT=none      # → None
```

## Provider-Specific Configuration

Dynamic provider names are fully supported:

```bash
# Configure OpenAI provider
VT_PROVIDERS_OPENAI_TYPE=openai
VT_PROVIDERS_OPENAI_API_KEY=sk-proj-xyz123
VT_PROVIDERS_OPENAI_ENDPOINT=https://api.openai.com

# Configure VoiceLive provider
VT_PROVIDERS_VOICELIVE_TYPE=voice_live
VT_PROVIDERS_VOICELIVE_API_KEY=your-api-key
VT_PROVIDERS_VOICELIVE_ENDPOINT=https://voicelive.example.com
VT_PROVIDERS_VOICELIVE_REGION=eastus

# Configure deeply nested settings
VT_PROVIDERS_VOICELIVE_SETTINGS_MODEL=gpt-realtime-mini
VT_PROVIDERS_VOICELIVE_SETTINGS_SESSION_OPTIONS_VOICE=alloy
VT_PROVIDERS_VOICELIVE_SETTINGS_SESSION_OPTIONS_TEMPERATURE=0.8
```

## Common Use Cases

### 1. Secrets Management

Store sensitive values in environment variables instead of YAML files:

```bash
# API Keys
VT_PROVIDERS_OPENAI_API_KEY=sk-proj-abc123
VT_PROVIDERS_VOICELIVE_API_KEY=your-secret-key

# Endpoints with credentials
VT_PROVIDERS_CUSTOM_ENDPOINT=https://user:pass@api.example.com
```

### 2. Environment-Specific Configuration

Override settings for different deployment environments:

```bash
# Development
VT_SYSTEM_LOG_LEVEL=DEBUG
VT_SYSTEM_LOG_WIRE=true

# Production
VT_SYSTEM_LOG_LEVEL=INFO
VT_SYSTEM_LOG_WIRE=false
VT_BUFFERING_INGRESS_QUEUE_MAX=10000
```

### 3. Dynamic Provider Selection

Switch providers without modifying YAML files:

```bash
VT_DISPATCH_DEFAULT_PROVIDER=voicelive
```

### 4. Performance Tuning

Adjust performance parameters:

```bash
VT_BUFFERING_INGRESS_QUEUE_MAX=5000
VT_BUFFERING_EGRESS_QUEUE_MAX=5000
VT_DISPATCH_BATCHING_MAX_BATCH_MS=300
VT_DISPATCH_BATCHING_IDLE_TIMEOUT_MS=1000
```

## Docker Compose Example

```yaml
services:
  vt-app:
    image: voice-translation:latest
    environment:
      # System configuration
      VT_SYSTEM_LOG_LEVEL: DEBUG
      VT_SYSTEM_LOG_WIRE: "true"

      # Provider configuration
      VT_DISPATCH_DEFAULT_PROVIDER: voicelive
      VT_PROVIDERS_VOICELIVE_API_KEY: ${VOICELIVE_API_KEY}
      VT_PROVIDERS_VOICELIVE_ENDPOINT: ${VOICELIVE_ENDPOINT}

      # Performance tuning
      VT_BUFFERING_INGRESS_QUEUE_MAX: "5000"
      VT_DISPATCH_BATCHING_ENABLED: "true"
```

## .env File Example

Create a `.env` file for local development:

```bash
# System Settings
VT_SYSTEM_LOG_LEVEL=DEBUG
VT_SYSTEM_LOG_WIRE=true
VT_SYSTEM_LOG_WIRE_DIR=logs/server

# Buffering Configuration
VT_BUFFERING_INGRESS_QUEUE_MAX=5000
VT_BUFFERING_EGRESS_QUEUE_MAX=5000
VT_BUFFERING_OVERFLOW_POLICY=DROP_OLDEST

# Dispatch Configuration
VT_DISPATCH_DEFAULT_PROVIDER=voicelive
VT_DISPATCH_BATCHING_ENABLED=true
VT_DISPATCH_BATCHING_MAX_BATCH_MS=200
VT_DISPATCH_BATCHING_MAX_BATCH_BYTES=65536
VT_DISPATCH_BATCHING_IDLE_TIMEOUT_MS=500

# Provider: VoiceLive
VT_PROVIDERS_VOICELIVE_TYPE=voice_live
VT_PROVIDERS_VOICELIVE_ENDPOINT=https://voicelive.example.com
VT_PROVIDERS_VOICELIVE_API_KEY=your-api-key-here
VT_PROVIDERS_VOICELIVE_REGION=eastus
VT_PROVIDERS_VOICELIVE_RESOURCE=voicelive-resource-name
VT_PROVIDERS_VOICELIVE_SETTINGS_MODEL=gpt-realtime-mini
VT_PROVIDERS_VOICELIVE_SETTINGS_API_VERSION=2024-10-01-preview
VT_PROVIDERS_VOICELIVE_SETTINGS_DEPLOYMENT=gpt-realtime-mini

# Provider: Live Interpreter
VT_PROVIDERS_LIVE_INTERPRETER_TYPE=live_interpreter
VT_PROVIDERS_LIVE_INTERPRETER_REGION=eastus2
VT_PROVIDERS_LIVE_INTERPRETER_API_KEY=your-api-key-here

# Provider: Mock (for testing)
VT_PROVIDERS_MOCK_TYPE=mock
```

## Limitations

### Lists/Arrays

Environment variable overrides for list values are **not supported** in v1. Lists defined in YAML cannot be overridden via environment variables and will be skipped.

**Example (NOT supported):**
```bash
# This will NOT work
VT_PROVIDERS_LIVE_INTERPRETER_SETTINGS_LANGUAGES=en-US,es-ES
```

**Workaround:** Define lists in YAML configuration files only.

## Error Handling

If an environment variable cannot be parsed, the server will **fail to start** with a clear error message:

```
ConfigError: Environment variable configuration error:
Failed to parse environment variable VT_BUFFERING_INGRESS_QUEUE_MAX:
Cannot parse 'not_a_number' as integer
```

This fail-fast behavior ensures configuration errors are caught immediately rather than causing runtime issues.

## Logging

When environment variables override configuration values, the server logs each override:

```
INFO: config_override_from_env var=VT_SYSTEM_LOG_LEVEL value_type=str path=system.log_level
INFO: config_override_from_env var=VT_PROVIDERS_OPENAI_API_KEY value_type=str path=providers.openai.api_key
```

This helps with debugging and understanding which configuration values are being overridden.

## Complete Configuration Reference

### System Configuration

```bash
VT_SYSTEM_LOG_LEVEL=INFO          # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
VT_SYSTEM_LOG_WIRE=false           # Enable wire-level logging
VT_SYSTEM_LOG_WIRE_DIR=logs/server # Wire log directory
```

### Buffering Configuration

```bash
VT_BUFFERING_INGRESS_QUEUE_MAX=2000      # Max ingress queue size
VT_BUFFERING_EGRESS_QUEUE_MAX=2000       # Max egress queue size
VT_BUFFERING_OVERFLOW_POLICY=DROP_OLDEST # Options: DROP_OLDEST, ...
```

### Dispatch Configuration

```bash
VT_DISPATCH_DEFAULT_PROVIDER=mock              # Default provider name
VT_DISPATCH_BATCHING_ENABLED=true              # Enable batching
VT_DISPATCH_BATCHING_MAX_BATCH_MS=200          # Max batch duration (ms)
VT_DISPATCH_BATCHING_MAX_BATCH_BYTES=65536     # Max batch size (bytes)
VT_DISPATCH_BATCHING_IDLE_TIMEOUT_MS=500       # Idle timeout (ms)
```

### Provider Configuration Template

```bash
VT_PROVIDERS_{NAME}_TYPE=...              # Provider type
VT_PROVIDERS_{NAME}_ENDPOINT=...          # API endpoint
VT_PROVIDERS_{NAME}_API_KEY=...           # API key
VT_PROVIDERS_{NAME}_REGION=...            # Region
VT_PROVIDERS_{NAME}_RESOURCE=...          # Resource name
VT_PROVIDERS_{NAME}_SETTINGS_{KEY}=...    # Provider-specific settings
```

Replace `{NAME}` with the provider name in UPPERCASE (e.g., `OPENAI`, `VOICELIVE`, `LIVE_INTERPRETER`).
