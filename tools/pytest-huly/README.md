# pytest-huly

The official Pytest plugin for integrating Python test suites with **Huly Test Management**.

Automatically captures test case executions, durations, failure traces, and statuses (`Passed`, `Failed`, `Blocked`), synchronizing them into Huly Test Management as rich `TestRun` and `TestResult` entities.

## Installation

```bash
pip install pytest-huly
```

Or install in development mode from this repository:
```bash
pip install -e tools/pytest-huly
```

## Quick Start

### 1. Environment Variables
Set your Huly instance credentials:

```bash
export HULY_URL="http://localhost:3332"
export HULY_WORKSPACE="your-workspace-uuid"
export HULY_TOKEN="your-api-token"
export HULY_PROJECT="24-character-hex-test-project-id"
```

### 2. Run Pytest with Huly reporting
```bash
pytest --huly
```

### 3. CLI Options
You can also pass credentials and custom run parameters directly:
```bash
pytest --huly \
  --huly-url="http://localhost:3332" \
  --huly-workspace="4722513f-801e-4581-9b62-677f59d58434" \
  --huly-token="eyJhbGci..." \
  --huly-project="673abc111111111111111111" \
  --huly-run-name="Release v1.2 Verification"
```

## Custom Markers

You can explicitly link pytest functions to Huly test cases or override the suite:

```python
import pytest

# Explicit link to an existing Huly TestCase
@pytest.mark.huly(case_id="673abc222222222222222222")
def test_order_checkout():
    assert process_checkout() == "success"

# Custom test suite grouping
@pytest.mark.huly(suite="Payment Gateway", priority="high")
def test_stripe_webhook():
    assert verify_signature() is True
```

## Standalone Ingestion Microservice

If using the companion `huly-test-ingest` microservice:
```bash
pytest --huly --huly-ingest-url="http://localhost:8095"
```
