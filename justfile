# Run tests
test:
    uv run pytest -xvs tests

# Serve documentation locally
docs:
    cd docs && npx --yes mint@latest dev
