import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 300_000
MAX_REQUEST_BYTES = 16_384
DEMO_CREDENTIALS = (
    ("admin", "admin", "admin"),
    ("alex", "alex", "user"),
    ("sara", "sara", "user"),
)
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


def database_path():
    return Path(os.environ.get("DELIVERY_DB_PATH", ROOT / "delivery.sqlite3"))


@contextmanager
def database_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return hmac.compare_digest(actual, expected)


def initialize_database(path, announce=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    credentials = {}
    with database_connection(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'admin'))
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK (price_cents > 0),
                available INTEGER NOT NULL CHECK (available IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                total_cents INTEGER NOT NULL CHECK (total_cents > 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 20),
                unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0)
            );
            """
        )
        for username, password, role in DEMO_CREDENTIALS:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    role = excluded.role
                """,
                (username, hash_password(password), role),
            )
            credentials[username] = password
        if connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO products (name, price_cents, available) VALUES (?, ?, 1)",
                [
                    ("Fresh apples", 399),
                    ("Sourdough bread", 550),
                    ("Olive oil", 1299),
                ],
            )
    if announce:
        print("Trial demo credentials (local testing only):")
        for username, password in credentials.items():
            print(f"  {username}: {password}")
    return credentials


def authenticate(path, username, password):
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    with database_connection(path) as connection:
        row = connection.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None or not verify_password(password, row[2]):
        return None
    return {"id": row[0], "username": row[1], "role": row[3]}


def get_products(path):
    with database_connection(path) as connection:
        rows = connection.execute(
            "SELECT id, name, price_cents, available FROM products ORDER BY id"
        ).fetchall()
    return [
        {"id": row[0], "name": row[1], "price_cents": row[2], "available": bool(row[3])}
        for row in rows
    ]


def create_order(path, user_id, items):
    if not isinstance(items, list) or not items or len(items) > 20:
        raise ValueError("An order must contain between 1 and 20 different items.")
    normalized = []
    seen_product_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each order item must be an object.")
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        if type(product_id) is not int or type(quantity) is not int:
            raise ValueError("Product IDs and quantities must be whole numbers.")
        if product_id in seen_product_ids:
            raise ValueError("An order cannot contain duplicate products.")
        if not 1 <= quantity <= 20:
            raise ValueError("Each quantity must be between 1 and 20.")
        seen_product_ids.add(product_id)
        normalized.append((product_id, quantity))

    with database_connection(path) as connection:
        order_lines = []
        total_cents = 0
        for product_id, quantity in normalized:
            product = connection.execute(
                "SELECT name, price_cents, available FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
            if product is None or not product[2]:
                raise ValueError("A selected product is unavailable.")
            name, price_cents, _ = product
            total_cents += price_cents * quantity
            order_lines.append((name, quantity, price_cents))
        cursor = connection.execute(
            "INSERT INTO orders (user_id, total_cents) VALUES (?, ?)",
            (user_id, total_cents),
        )
        order_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO order_items (order_id, product_name, quantity, unit_price_cents)
            VALUES (?, ?, ?, ?)
            """,
            [(order_id, name, quantity, price) for name, quantity, price in order_lines],
        )
    return order_id


def update_product(path, role, product_id, name, price_cents, available):
    if role != "admin":
        raise PermissionError("Administrator access is required.")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name.strip()) > 80
        or type(price_cents) is not int
        or not 1 <= price_cents <= 10_000_000
        or type(available) is not bool
    ):
        raise ValueError("Provide a valid product name, price, and availability.")
    with database_connection(path) as connection:
        cursor = connection.execute(
            """
            UPDATE products SET name = ?, price_cents = ?, available = ?
            WHERE id = ?
            """,
            (name.strip(), price_cents, int(available), product_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("Product not found.")


def get_orders(path, user_id, role):
    with database_connection(path) as connection:
        if role == "admin":
            rows = connection.execute(
                """
                SELECT orders.id, users.username, orders.total_cents, orders.created_at
                FROM orders JOIN users ON users.id = orders.user_id
                ORDER BY orders.id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT orders.id, users.username, orders.total_cents, orders.created_at
                FROM orders JOIN users ON users.id = orders.user_id
                WHERE orders.user_id = ?
                ORDER BY orders.id DESC
                """,
                (user_id,),
            ).fetchall()
        result = []
        for row in rows:
            item_rows = connection.execute(
                """
                SELECT product_name, quantity, unit_price_cents
                FROM order_items WHERE order_id = ? ORDER BY id
                """,
                (row[0],),
            ).fetchall()
            result.append(
                {
                    "id": row[0],
                    "username": row[1],
                    "total_cents": row[2],
                    "created_at": row[3],
                    "items": [
                        {
                            "name": item[0],
                            "quantity": item[1],
                            "unit_price_cents": item[2],
                        }
                        for item in item_rows
                    ],
                }
            )
    return result



def get_order_by_id(path, order_id):
    with database_connection(path) as connection:
        row = connection.execute(
            """
            SELECT orders.id, users.username, orders.total_cents, orders.created_at
            FROM orders JOIN users ON users.id = orders.user_id
            WHERE orders.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        items = connection.execute(
            "SELECT product_name, quantity, unit_price_cents FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
    return {
        "id": row[0], "username": row[1], "total_cents": row[2], "created_at": row[3],
        "items": [
            {"name": item[0], "quantity": item[1], "unit_price_cents": item[2]}
            for item in items
        ],
    }


def session_for(handler):
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("Cookie", ""))
    morsel = cookie.get("session")
    if morsel is None:
        return None, None
    token = morsel.value
    now = time.time()
    with SESSIONS_LOCK:
        session = SESSIONS.get(token)
        if session is None:
            return None, token
        if session["expires_at"] <= now:
            del SESSIONS[token]
            return None, token
        session["expires_at"] = now + SESSION_TTL_SECONDS
        return session["user"], token


class DeliveryHandler(BaseHTTPRequestHandler):
    server_version = "DeliveryDemo/1.0"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def send_json(self, status, value, extra_headers=()):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request length.") from error
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is empty or too large.")
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error

    def do_GET(self):
        path = urlparse(self.path).path
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            body = (ROOT / "static" / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/products":
            self.send_json(200, {"products": get_products(database_path())})
            return
        user, _ = session_for(self)
        if path == "/api/me":
            if user is None:
                self.send_json(200, {"user": None})
            else:
                self.send_json(200, {"user": user})
            return
        if path.startswith("/api/orders/"):
            if user is None:
                self.send_json(401, {"error": "Sign in to view orders."})
                return
            try:
                order_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                self.send_json(400, {"error": "Invalid order ID."})
                return
            order = get_order_by_id(database_path(), order_id)
            if order is None:
                self.send_json(404, {"error": "Order not found."})
                return
            self.send_json(200, {"order": order})
            return
        if path == "/api/orders":
            if user is None:
                self.send_json(401, {"error": "Sign in to view orders."})
                return
            self.send_json(
                200, {"orders": get_orders(database_path(), user["id"], user["role"])}
            )
            return
        self.send_json(404, {"error": "Not found."})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            try:
                data = self.read_json()
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
                return
            user = authenticate(
                database_path(), data.get("username"), data.get("password")
            ) if isinstance(data, dict) else None
            if user is None:
                self.send_json(401, {"error": "Invalid username or password."})
                return
            token = secrets.token_urlsafe(32)
            with SESSIONS_LOCK:
                SESSIONS[token] = {
                    "user": user,
                    "expires_at": time.time() + SESSION_TTL_SECONDS,
                }
            self.send_json(
                200,
                {"user": user},
                (
                    (
                        "Set-Cookie",
                        f"session={token}; HttpOnly; SameSite=Strict; Path=/; "
                        f"Max-Age={SESSION_TTL_SECONDS}",
                    ),
                ),
            )
            return
        if path == "/api/logout":
            user, token = session_for(self)
            if token is not None:
                with SESSIONS_LOCK:
                    SESSIONS.pop(token, None)
            self.send_json(
                200,
                {"ok": True},
                (("Set-Cookie", "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"),),
            )
            return
        user, _ = session_for(self)
        if user is None:
            self.send_json(401, {"error": "Sign in first."})
            return
        if path == "/api/orders":
            try:
                data = self.read_json()
                if not isinstance(data, dict):
                    raise ValueError("Request body must be an object.")
                order_id = create_order(
                    database_path(), user["id"], data.get("items")
                )
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
                return
            self.send_json(201, {"order_id": order_id})
            return
        if path.startswith("/api/admin/products/"):
            if user["role"] != "admin":
                self.send_json(403, {"error": "Administrator access is required."})
                return
            try:
                product_id = int(path.rsplit("/", 1)[1])
                data = self.read_json()
                if not isinstance(data, dict):
                    raise ValueError("Request body must be an object.")
                update_product(
                    database_path(),
                    user["role"],
                    product_id,
                    data.get("name"),
                    data.get("price_cents"),
                    data.get("available"),
                )
            except (ValueError, LookupError) as error:
                self.send_json(400 if isinstance(error, ValueError) else 404, {"error": str(error)})
                return
            self.send_json(200, {"ok": True})
            return
        self.send_json(404, {"error": "Not found."})

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


def main():
    path = database_path()
    initialize_database(path, announce=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DeliveryHandler)
    print(f"Delivery demo running at http://127.0.0.1:8000 (database: {path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
