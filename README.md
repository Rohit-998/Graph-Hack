# Firebreak

The AI incident commander that thinks in graphs. Stop incidents from spreading.

Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB). Tracks 01, 02 and 03.

Firebreak puts a company's operational context (services, dependencies, deploys, people, on-call,
customers, runbooks, past incidents) into a single FalkorDB knowledge graph. A small agent team
(Commander, Detective, Responder) works that graph during a live incident to find the root cause,
size the blast radius, and page the right people, with a clickable evidence path for every verdict.

> Work in progress. See [docs/PRD.md](docs/PRD.md) for the full spec.

## Quick start

```bash
docker compose up -d falkordb
cd backend
uv sync
uv run python -m firebreak.seed
```

FalkorDB Browser: http://localhost:3000

## AI assistance disclosure

This project is built with the help of an AI coding assistant.
