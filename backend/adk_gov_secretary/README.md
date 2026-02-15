# Gov Secretary ADK Agent

`adk_gov_secretary.agent` defines the Agent SDK root agent used by
`/v1/assistant/chat`.

## Tools

- `list_supported_domains`
- `search_municipality_candidates`
- `search_target_municipalities` (fallback from `backend/app/batch/targets.json`)
- `recommend_programs` (bridges existing `RecommendationEngine`)

## Required env vars

- `GOOGLE_API_KEY` (or legacy `GEMINI_API_KEY`)
- Optional: `ADK_MODEL` (default: `gemini-2.5-flash`)
- Optional Vertex mode:
  - `GOOGLE_GENAI_USE_VERTEXAI=true`
  - `GOOGLE_CLOUD_PROJECT`
  - `GOOGLE_CLOUD_LOCATION`
