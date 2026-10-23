# Good Basket Delivery

A small, local delivery-app demo for evaluating an AI pull-request reviewer. It includes customer and administrator roles, a product catalogue, order placement, and an admin-only product editor.

## Run locally

Requires Python 3.9 or newer; the app uses only the Python standard library.

```powershell
py app.py
```

Open <http://127.0.0.1:8000>. The trial credentials are `admin` / `admin` and `alex` / `alex`; the server prints them at startup. Passwords are stored as salted PBKDF2 hashes. On startup, the demo accounts are reset to these trial passwords. The server binds to localhost and places its SQLite database in `delivery.sqlite3`.

These fixed, easy passwords are intentionally insecure and are for local trials only. Do not expose this demonstration server to the public internet or reuse these credentials. The app does not implement production account management, deployment, or operational controls.

## Checks

Run the test suite with:

```powershell
py -m unittest -v
```

The tests cover parameterized login lookup, server-calculated order totals, quantity validation, customer/admin separation, and product availability.

## Reviewer benchmark

`review-cases.json` contains ticket requirements, review prompts, and expected findings for authorization, business logic, SQL safety, and credential handling. They are inert evaluation scenarios—not executable vulnerable patches. The application itself demonstrates the safe behavior the reviewer should expect. No intentionally exploitable PRs have been added or published.
