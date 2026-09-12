FROM python:3.12-slim

# uv rather than pip, so the image gets exactly the dependency set uv.lock pins
# and CI tests against.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Installed from the build context, not cloned from a branch, so the image
# always matches the commit it was built from.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    TRANSPORT_MODE=http \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=9001

EXPOSE 9001

CMD ["python3", "-m", "calibre_mcp_server"]
