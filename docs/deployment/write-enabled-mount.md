# Deploying the MCP with write access

The image does not change. Only the volume mount does. This file exists so the deployment can be
copied by anyone, and because a read-write mount is the one thing that turns a read-only library tool
into something that can modify your Calibre database.

## The Dockerfile is unchanged

Read access reads `metadata.db`. Write access writes the same file. Nothing about the image changes,
so the existing build is still correct:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Pin to a ref, not main, so a rebuild is reproducible.
RUN pip install --no-cache-dir \
    git+https://github.com/gczobel/calibre_mcp_server.git@<tag-or-sha>

ENV TRANSPORT_MODE=http \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=9001

EXPOSE 9001

CMD ["python3", "-m", "calibre_mcp_server"]
```

Mounting is a run-time decision, not a build-time one. There is no `Dockerfile` change to make.

## The compose service

The only difference from the read-only deployment is the mount. Drop `:ro`.

```yaml
services:
  calibre-mcp:
    container_name: nas-mcp-calibre-mcp
    image: ghcr.io/gczobel/calibre-mcp:latest
    restart: unless-stopped
    environment:
      - CALIBRE_LIBRARY_PATH=/books
      - CALIBRE_DB_FILENAME=metadata.db
      - TRANSPORT_MODE=http
      - HTTP_HOST=0.0.0.0
      - HTTP_PORT=9001
    volumes:
      # read-write, because the server now writes read status
      - /path/to/your/calibre/library:/books
    ports:
      - "9001:9001"
```

Read-only deployments should keep `:ro`. Write access is the only reason to drop it, and it costs the
filesystem-level guarantee that the server cannot modify the library.

## Before you switch the mount

1. **The `#read` column must exist.** See `docs/read-status.md`. The server cannot create it.
2. **Back up `metadata.db`.** It is the entire blast radius: metadata writes never touch book files.
   One file to copy, and you can restore it. Calibre-Web's built-in metadata backup is controlled by
   its `schedule_metadata_backup` setting and is off by default.
3. **Calibre must not have the same library open.** Calibre keeps metadata in memory and writes it
   back, so an external write can be silently overwritten. Calibre-Web is not Calibre and does not do
   this, so a Calibre-Web container alongside this one is fine.
4. **Expect SQLite write contention, not corruption.** Calibre libraries use `journal_mode = delete`,
   not WAL, so writers exclude each other at whole-file granularity. A concurrent writer produces a
   `SQLITE_BUSY` that must be retried, not a damaged database.

## Verifying it worked

Mark a book read through the MCP, then read it back:

```sql
SELECT value FROM custom_column_<id> WHERE book = <book_id>
```

`1` means the write landed. If the column exists and the write returned success but this is empty, the
write did not commit.

An unchanged Calibre window is not a failed write: Calibre shows an outside write only after it
restarts. See `docs/deployment/read-state-in-other-apps.md`.
