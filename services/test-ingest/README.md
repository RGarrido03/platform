# Huly Test Ingestion Microservice

A standalone, high-performance bridge microservice for ingesting CI/CD test results (JUnit XML, Pytest JSON) directly into Huly Test Management.

## Features
- **JUnit XML Ingestion**: Standard `POST /api/v1/ingest/junit` parses XML reports from pytest, Jest, JUnit 5, Vitest, and Playwright.
- **Structured JSON Ingestion**: Direct `POST /api/v1/ingest/run` for rich programmatic reporting.
- **Auto-Provisioning**: Automatically creates missing `TestSuite`s and `TestCase`s in Huly.
- **Atomic Transactor Mutations**: Batches results using `TxApplyIf` over Huly Transactor's REST RPC API.

## Environment & Headers

Authentication is passed via standard headers:
- `X-Huly-Url`: Base URL of Huly Transactor (e.g. `http://localhost:3332`)
- `X-Huly-Workspace`: Target Workspace UUID
- `X-Huly-Token`: Personal Access Token / API Token

## Running Locally

```bash
pip install -r requirements.txt
uvicorn main:app --port 8095
```

## Running with Docker

```bash
docker build -t huly-test-ingest .
docker run -p 8095:8095 huly-test-ingest
```
