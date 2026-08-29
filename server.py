#!/usr/bin/env python3
"""
powblock - Ephemeral proof-of-work public storage server.
"""

import argparse
import http.server
import json
import re
import secrets
import sqlite3
import string
import sys
import threading
import time
from hashlib import sha256
from typing import Optional

CROCKFORD_32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_REGEX = re.compile(r"^[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{26}$", re.IGNORECASE)


def decode_crockford_timestamp(s: str) -> int:
    """Decode a 10-character Crockford Base32 string into millisecond integer."""
    val = 0
    for char in s.upper():
        idx = CROCKFORD_32.find(char)
        if idx == -1:
            raise ValueError(f"Invalid Crockford Base32 character: {char}")
        val = (val << 5) | idx
    return val


class Database:
    """Thread-safe SQLite database manager."""

    def __init__(self, db_path: str = "powblocks.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS powblocks (
                    uuid TEXT PRIMARY KEY COLLATE BINARY CHECK (length(uuid) = 26),
                    content BLOB NOT NULL CHECK (length(content) <= 65536),
                    modified INTEGER NOT NULL,
                    expires INTEGER NOT NULL,
                    src_ip TEXT NOT NULL,
                    secret_hash BLOB NOT NULL CHECK (length(secret_hash) = 32)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expires ON powblocks(expires);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ip_modified ON powblocks(src_ip, modified);"
            )
        conn.close()

    def vacuum_expired(self) -> int:
        now = int(time.time())
        conn = self.get_conn()
        with conn:
            cursor = conn.execute(
                "DELETE FROM powblocks WHERE expires <= ?", (now,)
            )
            return cursor.rowcount


class PowBlockHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    db: Database = None
    work_factor: int = 1000
    ip_creation_lock = threading.Lock()
    ip_last_creation = {}

    def _send_cors_headers(self):
        """Append CORS headers to allow requests from any origin."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self._send_cors_headers()
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        """Handle CORS preflight requests from web browsers."""
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def get_client_ip(self) -> str:
        return self.client_address[0]

    def _extract_bearer_secret(self) -> Optional[str]:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        secret = auth_header[7:].strip()
        if not (1 <= len(secret) <= 32):
            return None
        if not all(c in string.printable and c not in "\r\n\t" for c in secret):
            return None
        return secret

    def do_GET(self):
        # Serve static HTML files if they exist in the current directory
        path = self.path.split("?", 1)[0]
        if path == "/":
            file_path = "index.html"
        else:
            file_path = path.lstrip("/")

        # Prevent path traversal outside current directory and check if file exists
        if file_path and not (".." in file_path or file_path.startswith("/") or file_path.startswith("\\")):
            import os
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "rb") as f:
                        content_bytes = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content_bytes)))
                    self._send_cors_headers()
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(content_bytes)
                    return
                except Exception:
                    pass

        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "powblocks":
            self.send_json(404, {"error": "Not Found"})
            return

        uuid_str = parts[1].upper()
        if not ULID_REGEX.match(uuid_str):
            self.send_json(400, {"error": "Invalid ULID format"})
            return

        now = int(time.time())
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT content, expires FROM powblocks WHERE uuid = ?", (uuid_str,)
        ).fetchone()

        if not row or row["expires"] <= now:
            if row and row["expires"] <= now:
                with conn:
                    conn.execute("DELETE FROM powblocks WHERE uuid = ?", (uuid_str,))
            self.send_json(404, {"error": "Block not found or expired"})
            return

        content = row["content"].decode("utf-8", errors="replace")
        self.send_json(200, {"content": content})

    def do_PUT(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "powblocks":
            self.send_json(404, {"error": "Not Found"})
            return

        uuid_str = parts[1].upper()
        if not ULID_REGEX.match(uuid_str):
            self.send_json(400, {"error": "Invalid ULID format"})
            return

        # Validate ULID timestamp freshness (within 5 minutes)
        try:
            ulid_time_ms = decode_crockford_timestamp(uuid_str[:10])
            now_ms = int(time.time() * 1000)
            if abs(now_ms - ulid_time_ms) > 300_000:
                self.send_json(400, {"error": "ULID timestamp outside allowed window"})
                return
        except ValueError:
            self.send_json(400, {"error": "Malformed ULID timestamp"})
            return

        secret = self._extract_bearer_secret()
        if not secret:
            self.send_json(
                401,
                {
                    "error": "Missing or invalid Bearer secret (printable ASCII up to 32 bytes)"
                },
            )
            return
        secret_hash = sha256(secret.encode("ascii")).digest()

        # Read JSON payload
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len <= 0 or content_len > 131072:
                self.send_json(400, {"error": "Invalid Content-Length"})
                return
            body = self.rfile.read(content_len)
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_json(400, {"error": "Malformed JSON payload"})
            return

        content = payload.get("content")
        hours = payload.get("hours")
        modified = payload.get("modified")
        nonce = payload.get("nonce")

        if (
            content is None
            or hours is None
            or modified is None
            or nonce is None
        ):
            self.send_json(400, {"error": "Missing required fields"})
            return

        if not isinstance(content, str) or not isinstance(hours, int) or hours < 1:
            self.send_json(400, {"error": "Invalid content or hours"})
            return

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > 65536:
            self.send_json(400, {"error": "Content exceeds 64KB limit"})
            return

        modified_val = modified
        if not isinstance(modified, int) or isinstance(modified, bool) or modified < 0:
            self.send_json(400, {"error": "Invalid modified timestamp"})
            return

        modified_str = str(modified)

        # PoW Check
        pow_payload = f"{uuid_str}{modified_str}{content}{nonce}".encode("utf-8")
        computed_hash_bytes = sha256(pow_payload).digest()

        computed_int = int.from_bytes(computed_hash_bytes, "big")
        bytes_count = len(content_bytes)
        target = (2**256) // (self.work_factor * max(bytes_count, 256) * max(hours, 1))

        if computed_int >= target:
            self.send_json(400, {"error": "PoW difficulty target not satisfied"})
            return

        now = int(time.time())
        client_ip = self.get_client_ip()
        conn = self.db.get_conn()

        row = conn.execute(
            "SELECT secret_hash, modified, expires FROM powblocks WHERE uuid = ?",
            (uuid_str,),
        ).fetchone()

        if row is None:
            # Creation
            with self.ip_creation_lock:
                last_time = self.ip_last_creation.get(client_ip, 0)
                if now - last_time < 60:
                    self.send_json(
                        429, {"error": "Rate limit exceeded (1 creation/min per IP)"}
                    )
                    return

                recent_count = conn.execute(
                    "SELECT COUNT(*) as c FROM powblocks WHERE src_ip = ? AND modified > ?",
                    (client_ip, now - 60),
                ).fetchone()["c"]
                if recent_count > 0:
                    self.send_json(
                        429, {"error": "Rate limit exceeded (1 creation/min per IP)"}
                    )
                    return

                self.ip_last_creation[client_ip] = now

            expires = now + (hours * 3600)
            with conn:
                conn.execute(
                    """
                    INSERT INTO powblocks (uuid, content, modified, expires, src_ip, secret_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_str,
                        content_bytes,
                        modified_val,
                        expires,
                        client_ip,
                        secret_hash,
                    ),
                )
            self.send_json(201, {"expires": expires})
        else:
            # Update
            if not secrets.compare_digest(row["secret_hash"], secret_hash):
                self.send_json(403, {"error": "Forbidden: invalid secret"})
                return

            if modified_val <= row["modified"]:
                self.send_json(
                    400,
                    {
                        "error": f"Conflict: modified ({modified_val}) must be > stored modified ({row['modified']})"
                    },
                )
                return

            expires = now + (hours * 3600)

            with conn:
                conn.execute(
                    """
                    UPDATE powblocks
                    SET content = ?,
                        modified = ?,
                        expires = ?
                    WHERE uuid = ?
                    """,
                    (content_bytes, modified_val, expires, uuid_str),
                )
            self.send_json(200, {"expires": expires})


def vacuum_worker(db: Database, interval_sec: int = 30):
    while True:
        try:
            db.vacuum_expired()
        except Exception as e:
            sys.stderr.write(f"Vacuum error: {e}\n")
        time.sleep(interval_sec)


def run_server():
    parser = argparse.ArgumentParser(description="Run powblock storage server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--db", default="powblocks.db", help="SQLite database path")
    parser.add_argument(
        "--work-factor",
        type=int,
        default=1000,
        help="PoW work factor difficulty constant (default: 1000)",
    )
    args = parser.parse_args()

    db = Database(args.db)
    PowBlockHandler.db = db
    PowBlockHandler.work_factor = args.work_factor

    vac_thread = threading.Thread(target=vacuum_worker, args=(db, 30), daemon=True)
    vac_thread.start()

    server = http.server.ThreadingHTTPServer((args.host, args.port), PowBlockHandler)
    print(f"powblock listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()


if __name__ == "__main__":
    run_server()