# Colinas Cafés — ERP & BI

Integrated management system (simplified ERP) and Business Intelligence layer for **Colinas Cafés**, a small coffee producer and micro-roaster from the Agreste region of Pernambuco, Brazil.

This is the practical project of the course **Sistemas de Informação e Tecnologias** (BSc in Computer Science, UFAPE, 2026.2, Prof. Dr. Assuero Fonseca Ximenes). Its goal is to simulate, at a reduced but realistic scale, the full cycle of an information system: **Operations → Data → Decision**.

> The user interface is in **Portuguese**, since it is meant for a Brazilian business. Code, database and repository documentation are in English.

## The business

Colinas Cafés grows arabica coffee on its own farm and buys green coffee lots from partner farms. It roasts in small batches, packs the coffee in valve bags (whole bean or ground) and sells **only roasted coffee** through three channels:

| Channel | Customers | Characteristics |
|---|---|---|
| **Local** | End consumers at the shop counter | Pickup or local delivery; PIX, cash or cards |
| **Online** | End consumers ordering digitally | Shipped in boxes; PIX or credit card |
| **Wholesale (B2B)** | Coffee shops, restaurants, emporiums, companies | Minimum order, wholesale price list, bank slip with payment terms and credit limit |

Before the system, stock, roasting, orders and bills lived in disconnected spreadsheets. As a result, stock levels diverged, the real cost per bag was unknown (roast weight loss was ignored), there was no batch traceability, packaging ran out and there was no financial visibility. The system addresses each of these problems.

## Project deliverables

1. **1st evaluation (VA1): operational layer (ERP).** Integrated transactional modules with Google sign-in, PostgreSQL persistence and public deployment.
2. **2nd evaluation (VA2): analytical layer (BI).** KPIs, interactive dashboards and a management analysis built **exclusively** on the data produced by the ERP.

## Modules

| Module | Scope | Status |
|---|---|---|
| Authentication & access control | Google sign-in, user allow-list, roles, role-based navigation, audit trail | ✅ Sign-in, roles and user management |
| Master data | Farms, suppliers, green coffees, packaging, products (SKUs), customers, financial categories and accounts | ✅ CRUD with search, deactivation and CPF/CNPJ validation |
| Purchasing | Purchase orders, receiving, cancellation and reversal, installment payables | ✅ Orders, receiving with freight allocation, cancellation, reversal |
| Inventory | Stock positions, movement ledger, minimum-stock alerts, inventory adjustments, storage location | ✅ Single movement path with weighted average cost, positions, ledger, adjustments |
| Production | Own harvest intake, roasting (weight loss and cost), packing (bag cost, freshness) | ✅ Harvest with payable, roasting with weight-loss limits, packing with batch compatibility, batch closing, freshness alerts |
| Sales | Quotes, orders, invoicing, shipping, delivery, cancellation, receipts | Planned |
| Finance | Payables and receivables, operating expenses, settlement, cash flow, reconciliation, income statement | 🟡 Payables from purchases and entry list |
| Administration | Users, settings, data integrity panel | 🟡 Users and integrity panel (stock, purchase and production checks) |
| Business Intelligence (VA2) | Analytical views, KPIs, dashboards, alerts | Planned |

Every integrated operation runs in a **single database transaction**, so receiving a purchase, roasting, packing or confirming a sale either updates stock, finance and history together or changes nothing.

## Tech stack

| Layer | Technology |
|---|---|
| UI / application | Python 3.12, Streamlit 1.67 (native OIDC authentication with Google) |
| Data access | psycopg 3 + psycopg-pool, parameterized SQL, explicit transactions |
| Database | PostgreSQL 16 (Supabase in production, Docker locally) |
| Deployment | Streamlit Community Cloud, continuous deployment from `main` |
| Quality | pytest (unit + integration against a real PostgreSQL), ruff |

## Architecture

```
ui/  ──►  services/  ──►  domain/          (pure business rules and calculations)
                     └─►  repositories/  ──►  PostgreSQL
```

- **`ui/`**: Streamlit pages and widgets. Never contains SQL or business rules.
- **`services/`**: use cases. They check permissions, open **the** transaction and orchestrate repositories and domain rules.
- **`domain/`**: entities, enums, permissions and calculations. No database or Streamlit imports, so it is easy to unit test.
- **`repositories/`**: parameterized SQL. They receive a connection and never commit.
- **`core/`**: configuration, connection pool and transaction helper, application errors.

### Repository layout

```
colinas-cafes-erp/
├── app.py                     # entrypoint: page config, sign-in, role-based navigation
├── core/                      # config, db (pool, transaction), errors
├── domain/                    # business rules (access.py: roles, permissions, users)
├── repositories/              # SQL access per aggregate
├── services/                  # transactional use cases
├── ui/                        # session, layout, navigation, labels (pt-BR), formatting
│   └── pages/                 # one module per page
├── sql/                       # ordered migrations: 001_schema.sql, 002_reference_data.sql, ...
├── scripts/migrate.py         # applies pending migrations
├── tests/
│   ├── unit/                  # domain tests, no database
│   └── integration/           # services against a disposable *_test database
├── docker-compose.yml         # local PostgreSQL with colinas_dev and colinas_test databases
└── .streamlit/                # config.toml and secrets.example.toml
```

## Getting started

### Prerequisites

- Python **3.12**
- Docker (or Podman) with Compose, for the local database
- A Google Cloud project with an OAuth client, for sign-in (see below)

### 1. Install dependencies

```bash
git clone https://github.com/P3DROVFX/colinas-cafes-erp.git
cd colinas-cafes-erp
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. Start the local database

```bash
docker compose up -d
```

This starts PostgreSQL 16 on `localhost:5432` (user and password `colinas`) with two databases: `colinas_dev` for running the app and `colinas_test` for integration tests. If port 5432 is already in use, change the host port in `docker-compose.yml` and in your connection URLs.

### 3. Configure Google sign-in and secrets

1. In the [Google Cloud Console](https://console.cloud.google.com/), configure the **OAuth consent screen** (External, scopes `openid`, `email`, `profile`).
2. Create an **OAuth client ID** of type *Web application* with the authorized redirect URI `http://localhost:8501/oauth2callback`.
3. Copy the secrets template and fill it in:

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
```

| Key | Description |
|---|---|
| `auth.redirect_uri` | `http://localhost:8501/oauth2callback` locally, `https://<app>.streamlit.app/oauth2callback` in production |
| `auth.cookie_secret` | Long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `auth.google.client_id` / `client_secret` | From the OAuth client |
| `database.url` | PostgreSQL connection URL (the local default is already set) |
| `app.admin_emails` | Emails that become **ADMIN** on their first sign-in |

`.streamlit/secrets.toml` is git-ignored. Never commit it.

### 4. Apply migrations

```bash
python -m scripts.migrate
```

The database URL comes from the `DATABASE_URL` environment variable or, if that is not set, from `[database].url` in `.streamlit/secrets.toml`. Running it again only applies new migrations.

### 5. Run the app

```bash
streamlit run app.py
```

Open http://localhost:8501 and sign in with Google. Emails listed in `admin_emails` sign in as administrators. Any other Google account is created as **Visitante** (read-only) and can be promoted in *Administração → Usuários*.

## Tests and linting

```bash
pytest tests/unit                                                                  # no database needed
TEST_DATABASE_URL=postgresql://colinas:colinas@localhost:5432/colinas_test pytest  # full suite
ruff check . && ruff format --check .
```

Integration tests **drop and recreate** the `public` schema of the test database before running. As a safeguard, they refuse any database whose name does not end in `_test`.

## Database

- `sql/001_schema.sql` is the source of truth for the physical model: tables, foreign keys, CHECK constraints, indexes, `updated_at` triggers and row level security.
- `sql/002_reference_data.sql` loads data every environment needs: settings, financial categories, cash and bank accounts, and the generic "Consumidor Final" customer.
- Migrations are named `NNN_description.sql`, applied in order and recorded in `schema_migrations`. Once a migration has run in a shared environment, it is never edited. Changes go in a new migration.
- A **seed script** for development and test databases (`scripts/seed.py`, months of realistic operations generated through the service layer) is planned. It will never run against production unless that is explicitly requested.

## Deployment

1. **Supabase:** create a project in the São Paulo region and copy the **Session pooler** connection string (`aws-0-sa-east-1.pooler.supabase.com:5432`, user `postgres.<project-ref>`, `sslmode=require`). Do not use the direct connection: it is IPv6-only, and Streamlit Community Cloud has no IPv6. Run `DATABASE_URL=<pooler-url> python -m scripts.migrate`.
2. **Google OAuth:** add `https://<app>.streamlit.app/oauth2callback` as a redirect URI and **publish the consent screen to production**. In *Testing* mode, only listed test users can sign in.
3. **Streamlit Community Cloud:** create an app from this repository (branch `main`, file `app.py`, Python 3.12) and paste the production secrets in *Advanced settings*.
4. Free Supabase projects pause after about a week of inactivity, and idle Streamlit apps go to sleep. Open the app ahead of any evaluation.

## Conventions

- **Language:** code, database identifiers and commits in English. Every user-facing text in Portuguese. Enum labels shown in the UI live in `ui/labels.py`.
- **Code:** small, single-purpose modules and functions with descriptive English names; `Decimal` for money and weights; no comments unless they explain a non-obvious *why*.
- **Errors:** business rule violations raise `AppError` subclasses with a message that is safe to show to the user. The UI displays them, and any other exception is a bug.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/), single-line English subject in the imperative mood (`feat: add purchase receiving`, `fix: prevent negative stock on packing`), no body.

## Roadmap

| Phase | Deliverable |
|---|---|
| 0. Foundation | Repository, schema, migrations, Google sign-in, roles, user management, deployment ✅ (deployment pending) |
| 1. Master data | CRUD for all master entities with deactivation of referenced records ✅ |
| 2. Inventory + purchasing | Stock ledger, weighted average cost, purchase receiving, payables ✅ |
| 3. Production | Own harvest, roasting, packing, freshness alerts ✅ |
| 4. Sales | Quote-to-delivery flow, cancellation with reversals, PDF receipts |
| 5. Finance + admin | Expenses, settlement, cash flow, reconciliation, income statement, settings, integrity panel |
| 6. VA1 delivery | Development seed, test coverage, technical documentation |
| 7–9. VA2 | Analytical views, dashboards, data analysis and recommendations |
