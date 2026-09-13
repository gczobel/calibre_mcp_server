# Calibre MCP Server
![License](https://img.shields.io/github/license/ajtudela/calibre_mcp_server)

An MCP (Model Context Protocol) server that provides tools to interact with a Calibre e-book library, allowing search and retrieval of book metadata through the MCP protocol.

### Tools
| Tool                            | Description                                            | Parameters           |
| ------------------------------- | ------------------------------------------------------ | -------------------- |
| **search_books_by_title**       | Search books by title pattern with wildcards           | `title_pattern: str` |
| **search_authors_by_name**      | Search authors by name pattern with wildcards          | `name_pattern: str`  |
| **get_books_by_author**         | Get all books by a specific author name                | `author_name: str`   |
| **get_books_by_author_id**      | Get all books by a specific author ID                  | `author_id: int`     |
| **get_books_by_series**         | Get all books in a series, ordered by index            | `series_name: str`   |
| **get_books_by_tag**            | Get all books with a specific tag                      | `tag_name: str`      |
| **search_books_by_tag_pattern** | Search books by tag pattern with wildcards             | `tag_pattern: str`   |
| **get_book_details**            | Get complete details for a specific book (incl. read, rating) | `book_id: int` |
| **find_books**                  | Find books by author, tag, series, rating, read state; returns count and matches | `author?, tag?, series?, rating_min?, rating_max?, read?, limit?` |
| **mark_book_read**              | Mark a book as read                                    | `book_id: int`       |
| **mark_book_unread**            | Mark a book as unread                                  | `book_id: int`       |
| **set_book_rating**             | Set a book's rating (1–5 stars)                        | `book_id: int, stars: int` |
| **get_library_stats**           | Get comprehensive library statistics                   | —                    |
| **get_all_tags**                | Get all available tags in the library                  | —                    |

## Configuration

The server supports flexible configuration through environment variables:

| Variable               | Default              | Description                                 |
| ---------------------- | -------------------- | ------------------------------------------- |
| `CALIBRE_LIBRARY_PATH` | —                    | **Required** path to Calibre library        |
| `CALIBRE_DB_FILENAME`  | `metadata.db`        | Database filename within library            |
| `CALIBRE_READ_COLUMN`  | `read`               | Lookup name of the Yes/No column used for read state |
| `LOG_LEVEL`            | `INFO`               | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT`           | Default format       | Custom logging format string                |
| `MCP_SERVER_NAME`      | `Calibre MCP Server` | Server name for MCP protocol                |
| `TRANSPORT_MODE`       | `stdio`              | Transport mode (`stdio` or `http`)          |
| `HTTP_HOST`            | `0.0.0.0`            | HTTP host when using HTTP transport         |
| `HTTP_PORT`            | `9001`               | HTTP port when using HTTP transport         |

### Environment Setup
1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` with your settings:
```bash
# Required
CALIBRE_LIBRARY_PATH=/path/to/your/calibre/library

# Optional
LOG_LEVEL=DEBUG
TRANSPORT_MODE=http
```

## Features
- **Advanced search capabilities**: Search books by title, author, series, and tags with wildcard support
- **Comprehensive metadata**: Retrieve complete book information including publication dates, series info, and tags
- **Read state and rating**: Mark books read or unread, set a 1–5 star rating, and see both on book details
- **Combined filtering**: `find_books` narrows by author, tag, series, rating range, and read state at once, and reports a count so an empty result is explicit
- **Library statistics**: Get insights into your Calibre library with comprehensive statistics
- **Tag management**: Browse and search through all available tags in your library
- **Author discovery**: Find authors and explore their complete bibliographies
- **Series tracking**: Access books in series with proper ordering by series index

## Read status

The server can mark a book read or unread, and it reads back the rating Calibre already stores.

Read state lives in a Calibre custom column **you create** — a **Yes/No** column with lookup name
`read` (Calibre shows it as `#read`). The server writes `1` for read and `0` for unread, and a book
with no entry counts as unread. It needs nothing but Calibre.

Create the column in Calibre: **Preferences → Add your own columns → Add custom column**, pick
**Yes/No**, and set the lookup name to `read`. If you already keep read state under a different
lookup name, set `CALIBRE_READ_COLUMN` to that name.

If the column is missing, reading still works — a book just reports no read state. Writing is
stricter: `mark_book_read` and `mark_book_unread` refuse and name the missing column.

Read status is written back to `metadata.db`, so mount the library read-write and don't have Calibre
itself open on the same library while you write. See `docs/deployment/write-enabled-mount.md`.

If you also run Calibre-Web, set its `config_read_column` to this column's numeric id and the two
share one read state. Nothing here requires Calibre-Web.

- Column contract and SQL: `docs/read-status.md`
- Read-write deployment: `docs/deployment/write-enabled-mount.md`

## Installation

### Install with uv (recommended)

Clone the repository and install with uv:

```bash
git clone https://github.com/ajtudela/calibre_mcp_server.git
cd calibre_mcp_server
cp .env.example .env
# Edit .env file with your Calibre library path
uv sync
```

Or install directly from the repository:

```bash
uv add git+https://github.com/ajtudela/calibre_mcp_server.git
```

### Install with pip

Install the package in mode:

```bash
git clone https://github.com/ajtudela/calibre_mcp_server.git
cd calibre_mcp_server
cp .env.example .env
# Edit .env file with your Calibre library path
python3 -m pip install .
```

Or install directly from the repository:

```bash
python3 -m pip install git+https://github.com/ajtudela/calibre_mcp_server.git
```

## Usage

### Running with uv

```bash
uv run calibre_mcp_server
```

### Running with pip installation

```bash
python3 -m calibre_mcp_server
```

### HTTP Mode (for containers)

To run in HTTP mode for containerized environments:

```bash
# Set environment variable
export TRANSPORT_MODE=http
export HTTP_HOST=0.0.0.0
export HTTP_PORT=9001
```

### Running from the container image

An image is published on every green push to `main`. A ready-to-paste compose file is at
`docker-compose.yml`:

```bash
git clone https://github.com/gczobel/calibre_mcp_server.git
cd calibre_mcp_server
# set the library path on the left of the volume line first
docker compose up -d
```

Or by hand:

```bash
docker run --rm -p 9001:9001 \
  -v /path/to/your/calibre/library:/books \
  -e CALIBRE_LIBRARY_PATH=/books \
  ghcr.io/gczobel/calibre_mcp_server:latest
```

It is a plain Compose file, so `docker compose up -d` works, and any Compose-capable host or manager
takes it unchanged. Set the library path on the left of the volume line first.

Note the mount has **no `:ro`**. Read tracking writes to `metadata.db`, so a read-only mount turns the
write tools into errors. Add `:ro` only if you will never call `mark_book_read`, `mark_book_unread` or
`set_book_rating`.

Don't have Calibre itself open on that library while writing. See
`docs/deployment/write-enabled-mount.md` for the preconditions and for what a concurrent write looks
like.

### Configuration example for Claude Desktop/Cursor/VSCode

#### Using uv (recommended)

Add this configuration to your application's settings (mcp.json):

```json
{
  "calibre mcp server": {
    "type": "stdio",
    "command": "uv",
    "args": [
      "run",
      "--directory",
      "/path/to/calibre_mcp_server",
      "calibre_mcp_server"
    ],
    "env": {
        "CALIBRE_LIBRARY_PATH": "YOUR_CALIBRE_LIBRARY_PATH"
    }
  }
}
```

#### Using pip installation

```json
{
  "calibre mcp server": {
    "type": "stdio",
    "command": "python3",
    "args": [
      "-m",
      "calibre_mcp_server"
    ],
    "env": {
        "CALIBRE_LIBRARY_PATH": "YOUR_CALIBRE_LIBRARY_PATH"
    }
  }
}
```

## Technical Notes
- **Database connection**: Automatic connection management with proper error handling
- **Configuration validation**: Startup validation ensures all required settings are present
- **SQLite optimization**: Efficient queries with proper indexing and connection pooling
- **Search patterns**: Support for SQL LIKE wildcards (%) for flexible pattern matching
- **Read and write access**: Reads are always available; write tools only touch the read column and rating tables, with a bounded lock timeout for concurrent writers
- **Memory efficient**: Optimized queries and proper resource cleanup
- **Error recovery**: Graceful handling of database errors and network issues

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes following the established patterns
4. Ensure all modules compile without errors
5. Update documentation as needed
6. Submit a pull request

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.