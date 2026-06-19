# One command regenerates the committed Flow docs from backend source catalogs.
docs\:regen:
	cd backend && set -a && . .env.template && set +a && uv run python scripts/generate_flow_docs.py
