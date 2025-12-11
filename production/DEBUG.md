# Remote Debugging Guide (PyCharm/IntelliJ)

## Overview

The production test framework supports remote debugging via PyCharm/IntelliJ IDEA's Python Debug Server. This allows you to set breakpoints, inspect variables, and step through code running inside a Docker container or on a remote machine.

---

## Setup Instructions

### 1. Configure PyCharm/IntelliJ Debug Server

#### Step 1: Install pydevd-pycharm
The debug server library should already be installed in the container. If needed:
```bash
pip install pydevd-pycharm
```

#### Step 2: Create a Python Debug Server Configuration

1. Open **Run/Debug Configurations** in PyCharm/IntelliJ
2. Click **+** → **Python Debug Server**
3. Configure:
   - **Name**: `Translation Remote Debug`
   - **IDE host name**: `localhost` (or your machine's IP if debugging from container)
   - **Port**: `5678` (or choose your own)
   - **Path mappings** (if needed):
     - Local: `/Users/yourname/dev/vt/vt-translations/test/production`
     - Remote: `/app/production` (adjust based on container mount)

4. Click **OK** to save

#### Step 3: Start the Debug Server

1. Click the debug configuration dropdown → Select **Translation Remote Debug**
2. Click the **Debug** button (or press Shift+F9)
3. PyCharm will show: `Waiting for process connection...`

**Keep this running** - the test framework will connect to it when you run tests.

### 2. Enable Remote Debugging in Configuration

#### Option A: Environment Variables (Recommended)

Set these in your shell or `.env` file:

```bash
# Enable debugging
export TRANSLATION_REMOTE_DEBUG=true

# Debug server connection (must match PyCharm config)
export TRANSLATION_DEBUG_HOST=localhost
export TRANSLATION_DEBUG_PORT=5678

# Optional: Pause execution until debugger attaches
export TRANSLATION_DEBUG_SUSPEND=false

# Optional: Redirect output to debugger console
export TRANSLATION_DEBUG_STDOUT=true
export TRANSLATION_DEBUG_STDERR=true
```

#### Option B: Update `.env` File

Copy `.env.sample` to `.env` and modify:

```bash
# ─── Remote Debugging (PyCharm/IntelliJ) ────────────────────────────────────

# Enable PyCharm remote debugging (true/false)
TRANSLATION_REMOTE_DEBUG=true

# Debug server host (where PyCharm/IntelliJ is running)
TRANSLATION_DEBUG_HOST=localhost

# Debug server port (must match PyCharm's "Python Debug Server" configuration)
TRANSLATION_DEBUG_PORT=5678

# Wait for debugger to attach before continuing execution (true/false)
TRANSLATION_DEBUG_SUSPEND=false
```

### 3. Run Your Tests

Execute tests as normal. The debug connection will be established automatically:

```bash
# Run a single test
python -m production.cli run-test scenarios/basic_conversation.yaml

# Run a suite
python -m production.cli run-suite scenarios/ --pattern "*.yaml"
```

**Output when debugging is enabled:**
```
INFO:production.utils.debug:Connecting to PyCharm debug server at localhost:5678 (suspend=False)
INFO:production.utils.debug:✓ Remote debugging enabled successfully
```

**In PyCharm:**
```
Connected to pydev debugger (build 233.11799.241)
```

---

## Setting Breakpoints

### In Production Code

1. Open any file in the `production/` directory
2. Click in the left gutter next to the line number
3. A red dot appears → breakpoint set
4. Run tests - execution will pause at the breakpoint

### In Scenario Engine

Example: Break when processing audio events

```python
# production/scenario_engine/engine.py

async def run(self, scenario: Scenario) -> tuple[Summary, list[Assertion]]:
    # ... existing code ...

    # Set breakpoint here to inspect scenario
    breakpoint()  # Or click in gutter

    for event in scenario.events:
        # Set breakpoint here to inspect each event
        await self._process_event(event)
```

---

## Debugging from Docker

If running tests inside a Docker container, you need to expose the debug connection to the host:

### Docker Run Example

```bash
docker run -it --rm \
  -v $(pwd):/app \
  -e TRANSLATION_REMOTE_DEBUG=true \
  -e TRANSLATION_DEBUG_HOST=host.docker.internal \
  -e TRANSLATION_DEBUG_PORT=5678 \
  your-image \
  python -m production.cli run-test scenarios/test.yaml
```

**Key changes:**
- `TRANSLATION_DEBUG_HOST=host.docker.internal` - Special Docker hostname for host machine
- If on Linux, use `--add-host=host.docker.internal:host-gateway`

### Docker Compose Example

```yaml
services:
  tests:
    build: .
    volumes:
      - .:/app
    environment:
      TRANSLATION_REMOTE_DEBUG: "true"
      TRANSLATION_DEBUG_HOST: host.docker.internal
      TRANSLATION_DEBUG_PORT: 5678
    extra_hosts:
      - "host.docker.internal:host-gateway"  # Linux only
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSLATION_REMOTE_DEBUG` | `false` | Enable/disable remote debugging |
| `TRANSLATION_DEBUG_HOST` | `localhost` | Hostname where PyCharm debug server is running |
| `TRANSLATION_DEBUG_PORT` | `5678` | Port where PyCharm debug server is listening |
| `TRANSLATION_DEBUG_SUSPEND` | `false` | Pause execution until debugger attaches |
| `TRANSLATION_DEBUG_STDOUT` | `true` | Redirect stdout to debugger console |
| `TRANSLATION_DEBUG_STDERR` | `true` | Redirect stderr to debugger console |

### Suspend Mode

**`TRANSLATION_DEBUG_SUSPEND=false` (Default)**
- Tests start immediately
- Debugger connects in background
- Can set breakpoints while tests are running

**`TRANSLATION_DEBUG_SUSPEND=true`**
- Tests pause at first line
- **Must attach debugger before tests proceed**
- Useful for debugging startup/initialization code

---

## Troubleshooting

### Issue 1: "Connection refused" or "Failed to enable remote debugging"

**Symptoms:**
```
ERROR:production.utils.debug:Failed to enable remote debugging: [Errno 61] Connection refused
```

**Solutions:**
1. ✅ Start PyCharm Debug Server **first** (see step 1.3)
2. ✅ Check port matches in both PyCharm and environment variable
3. ✅ Verify firewall allows connections on debug port
4. ✅ If in Docker, use `host.docker.internal` instead of `localhost`

### Issue 2: "pydevd_pycharm not available"

**Symptoms:**
```
WARNING:production.utils.debug:pydevd_pycharm not available - remote debugging disabled
```

**Solution:**
```bash
pip install pydevd-pycharm
```

Or ensure it's in `requirements.txt`:
```
pydevd-pycharm~=233.11799.241
```

### Issue 3: Breakpoints not hitting

**Possible causes:**
1. **Path mappings incorrect** in PyCharm Debug Server config
   - Local path and remote path must match your project structure
2. **Breakpoint in unreachable code**
   - Check logs to confirm code is actually executing
3. **Debug server not running**
   - Verify "Waiting for process connection..." message in PyCharm

**Solutions:**
- Check path mappings: **Run/Debug Configurations** → **Python Debug Server** → **Path mappings**
- Add logging before breakpoint to confirm code is reached:
  ```python
  logger.info("About to hit breakpoint")
  breakpoint()  # Set breakpoint here
  ```

### Issue 4: Tests hang indefinitely

**Symptom:** Tests don't start when `TRANSLATION_DEBUG_SUSPEND=true`

**Cause:** Debug server not running, but suspend mode enabled

**Solutions:**
- Start PyCharm Debug Server **before** running tests
- Or set `TRANSLATION_DEBUG_SUSPEND=false` to continue without debugger

---

## Usage Example

### Complete Workflow

```bash
# 1. Start PyCharm Debug Server
#    (In PyCharm: Run → Debug 'Translation Remote Debug')

# 2. Enable debugging in shell
export TRANSLATION_REMOTE_DEBUG=true
export TRANSLATION_DEBUG_HOST=localhost
export TRANSLATION_DEBUG_PORT=5678

# 3. Set breakpoints in PyCharm
#    Click gutter next to line numbers in production/*.py files

# 4. Run tests
python -m production.cli run-test scenarios/conversation.yaml

# 5. Execution pauses at breakpoints
#    - Inspect variables in PyCharm's debugger panel
#    - Step through code with F8 (step over) or F7 (step into)
#    - Resume with F9

# 6. Disable debugging when done
unset TRANSLATION_REMOTE_DEBUG
```

---

## Programmatic Usage

### In Custom Scripts

```python
from production.utils.config import load_config
from production.utils.debug import setup_remote_debugging

# Load configuration
config = load_config()

# Enable debugging (respects TRANSLATION_REMOTE_DEBUG env var)
if setup_remote_debugging(config):
    print("Debugger connected - set breakpoints in PyCharm")
else:
    print("Debugging disabled or unavailable")

# Your code here...
```

### Check if Debugging Enabled

```python
from production.utils.debug import is_debugging_enabled

if is_debugging_enabled():
    # Debugging is enabled, might want to:
    # - Log extra debug info
    # - Disable timeouts
    # - Skip certain optimizations
    pass
```

---

## Best Practices

### 1. Don't Commit Debug Configuration

Add to `.gitignore`:
```
.env
*.pyc
__pycache__/
.idea/  # PyCharm project files
```

### 2. Use Conditional Breakpoints

Instead of stopping at every iteration:
```python
for i, event in enumerate(events):
    # Only break on specific event
    if event.type == "audio_data" and event.silent:
        breakpoint()  # Conditional breakpoint in code
```

Or in PyCharm: Right-click breakpoint → **Edit** → Add condition

### 3. Disable for Production

**Never** enable debugging in production environments:
```bash
# Production .env should have:
TRANSLATION_REMOTE_DEBUG=false
```

### 4. Use Logging for Non-Interactive Debugging

When remote debugging isn't available:
```python
import logging
logger = logging.getLogger(__name__)

# Log variable state instead of using debugger
logger.debug(f"Processing event: {event.type}, data={event.data}")
```

---

## References

- [PyCharm Remote Debugging Documentation](https://www.jetbrains.com/help/pycharm/remote-debugging-with-product.html)
- [pydevd-pycharm PyPI](https://pypi.org/project/pydevd-pycharm/)
- [Docker and PyCharm Debugging](https://www.jetbrains.com/help/pycharm/using-docker-as-a-remote-interpreter.html)
