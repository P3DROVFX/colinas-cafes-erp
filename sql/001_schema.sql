CREATE TABLE users (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email          TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
  name           TEXT NOT NULL,
  role           TEXT NOT NULL DEFAULT 'VIEWER'
                 CHECK (role IN ('ADMIN','MANAGER','PRODUCTION','SALES','FINANCE','VIEWER')),
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at  TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by     TEXT
);

CREATE TABLE settings (
  key            TEXT PRIMARY KEY,
  value          TEXT,
  value_type     TEXT NOT NULL CHECK (value_type IN ('INT','DECIMAL','TEXT','BOOL','DATE')),
  description    TEXT NOT NULL,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by     TEXT
);

CREATE TABLE suppliers (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name            TEXT NOT NULL,
  person_type     TEXT NOT NULL CHECK (person_type IN ('PF','PJ')),
  document        TEXT NOT NULL UNIQUE CHECK (document ~ '^[0-9]{11}$|^[0-9]{14}$'),
  supply_type     TEXT NOT NULL CHECK (supply_type IN ('GREEN_COFFEE','PACKAGING','SERVICE')),
  email           TEXT,
  phone           TEXT,
  city            TEXT,
  state           CHAR(2),
  lead_time_days  INT NOT NULL DEFAULT 7 CHECK (lead_time_days >= 0),
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by      TEXT,
  CHECK ((person_type = 'PF' AND length(document) = 11) OR (person_type = 'PJ' AND length(document) = 14))
);

CREATE TABLE farms (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  city         TEXT NOT NULL,
  state        CHAR(2) NOT NULL,
  altitude_m   INT CHECK (altitude_m BETWEEN 0 AND 3000),
  producer     TEXT NOT NULL,
  is_own       BOOLEAN NOT NULL DEFAULT FALSE,
  supplier_id  BIGINT REFERENCES suppliers(id),
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by   TEXT,
  CHECK (is_own = (supplier_id IS NULL))
);

CREATE TABLE green_coffees (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  farm_id          BIGINT NOT NULL REFERENCES farms(id),
  variety          TEXT NOT NULL,
  process          TEXT NOT NULL CHECK (process IN ('NATURAL','PULPED_NATURAL','WASHED','FERMENTED')),
  harvest_year     INT NOT NULL CHECK (harvest_year BETWEEN 2020 AND 2100),
  sca_score        NUMERIC(4,2) CHECK (sca_score BETWEEN 60 AND 100),
  moisture_pct     NUMERIC(4,1) CHECK (moisture_pct BETWEEN 0 AND 20),
  min_stock_kg     NUMERIC(12,3) NOT NULL DEFAULT 0 CHECK (min_stock_kg >= 0),
  location         TEXT,
  stock_kg         NUMERIC(12,3) NOT NULL DEFAULT 0 CHECK (stock_kg >= 0),
  avg_cost_per_kg  NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (avg_cost_per_kg >= 0),
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by       TEXT,
  UNIQUE (farm_id, variety, process, harvest_year)
);

CREATE TABLE packaging_items (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  kind           TEXT NOT NULL CHECK (kind IN ('BAG','LABEL','SHIPPING_BOX')),
  capacity_g     INT,
  min_stock      INT NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
  location       TEXT,
  stock          INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
  avg_unit_cost  NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (avg_unit_cost >= 0),
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by     TEXT,
  CHECK ( (kind = 'BAG'          AND capacity_g IN (250, 500, 1000))
       OR (kind = 'SHIPPING_BOX' AND capacity_g > 0)
       OR (kind = 'LABEL'        AND capacity_g IS NULL) )
);

CREATE TABLE products (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sku              TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  green_coffee_id  BIGINT NOT NULL REFERENCES green_coffees(id),
  roast_profile    TEXT NOT NULL CHECK (roast_profile IN ('LIGHT','MEDIUM','DARK')),
  grind            TEXT NOT NULL CHECK (grind IN ('WHOLE_BEAN','ESPRESSO','FILTER','FRENCH_PRESS')),
  weight_g         INT NOT NULL CHECK (weight_g IN (250, 500, 1000)),
  bag_id           BIGINT NOT NULL REFERENCES packaging_items(id),
  label_id         BIGINT NOT NULL REFERENCES packaging_items(id),
  price_local      NUMERIC(12,2) NOT NULL CHECK (price_local > 0),
  price_online     NUMERIC(12,2) NOT NULL CHECK (price_online > 0),
  price_wholesale  NUMERIC(12,2) CHECK (price_wholesale > 0),
  min_stock        INT NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
  location         TEXT,
  stock            INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
  avg_unit_cost    NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (avg_unit_cost >= 0),
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by       TEXT,
  UNIQUE (green_coffee_id, roast_profile, grind, weight_g)
);

CREATE TABLE customers (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name               TEXT NOT NULL,
  person_type        TEXT NOT NULL CHECK (person_type IN ('PF','PJ')),
  document           TEXT UNIQUE CHECK (document ~ '^[0-9]{11}$|^[0-9]{14}$'),
  segment            TEXT NOT NULL DEFAULT 'CONSUMER'
                     CHECK (segment IN ('CONSUMER','COFFEE_SHOP','RESTAURANT','EMPORIUM','COMPANY')),
  email              TEXT,
  phone              TEXT,
  address            TEXT,
  city               TEXT,
  state              CHAR(2),
  payment_term_days  INT NOT NULL DEFAULT 0 CHECK (payment_term_days BETWEEN 0 AND 90),
  credit_limit       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
  is_active          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by         TEXT,
  CHECK (segment = 'CONSUMER' OR (person_type = 'PJ' AND document IS NOT NULL))
);

CREATE TABLE financial_categories (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  entry_type  TEXT NOT NULL CHECK (entry_type IN ('PAYABLE','RECEIVABLE')),
  dre_group   TEXT NOT NULL CHECK (dre_group IN
              ('REVENUE','OTHER_REVENUE','REFUND','INVENTORY','SELLING_COST','OPERATING_EXPENSE')),
  is_system   BOOLEAN NOT NULL DEFAULT FALSE,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE financial_accounts (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE,
  kind             TEXT NOT NULL CHECK (kind IN ('CASH','BANK')),
  opening_balance  NUMERIC(12,2) NOT NULL DEFAULT 0,
  opening_date     DATE NOT NULL,
  is_system        BOOLEAN NOT NULL DEFAULT FALSE,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE purchases (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  number           TEXT NOT NULL UNIQUE,
  supplier_id      BIGINT NOT NULL REFERENCES suppliers(id),
  status           TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','RECEIVED','CANCELLED','REVERSED')),
  order_date       DATE NOT NULL,
  expected_date    DATE,
  received_date    DATE,
  products_amount  NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (products_amount >= 0),
  freight_amount   NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (freight_amount >= 0),
  total_amount     NUMERIC(12,2) GENERATED ALWAYS AS (products_amount + freight_amount) STORED,
  installments     SMALLINT NOT NULL DEFAULT 1 CHECK (installments BETWEEN 1 AND 6),
  first_due_days   SMALLINT NOT NULL DEFAULT 30 CHECK (first_due_days >= 0),
  supplier_invoice TEXT,
  notes            TEXT,
  user_email       TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  received_by      TEXT,
  received_at      TIMESTAMPTZ,
  cancelled_by     TEXT,
  cancelled_at     TIMESTAMPTZ,
  cancel_reason    TEXT,
  CHECK (status <> 'RECEIVED' OR received_date IS NOT NULL),
  CHECK (status NOT IN ('CANCELLED','REVERSED') OR cancel_reason IS NOT NULL),
  CHECK (received_date IS NULL OR received_date >= order_date)
);

CREATE TABLE purchase_items (
  id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  purchase_id          BIGINT NOT NULL REFERENCES purchases(id),
  green_coffee_id      BIGINT REFERENCES green_coffees(id),
  packaging_item_id    BIGINT REFERENCES packaging_items(id),
  quantity             NUMERIC(12,3) NOT NULL CHECK (quantity > 0),
  unit_cost            NUMERIC(14,4) NOT NULL CHECK (unit_cost > 0),
  allocated_freight    NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (allocated_freight >= 0),
  effective_unit_cost  NUMERIC(14,4),
  CHECK (num_nonnulls(green_coffee_id, packaging_item_id) = 1)
);

CREATE TABLE harvests (
  id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  number               TEXT NOT NULL UNIQUE,
  green_coffee_id      BIGINT NOT NULL REFERENCES green_coffees(id),
  harvest_date         DATE NOT NULL,
  quantity_kg          NUMERIC(12,3) NOT NULL CHECK (quantity_kg > 0),
  total_cost           NUMERIC(12,2) NOT NULL CHECK (total_cost >= 0),
  cost_per_kg          NUMERIC(14,4) GENERATED ALWAYS AS (round(total_cost / quantity_kg, 4)) STORED,
  service_supplier_id  BIGINT REFERENCES suppliers(id),
  due_date             DATE NOT NULL,
  notes                TEXT,
  user_email           TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roast_batches (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               TEXT NOT NULL UNIQUE,
  green_coffee_id    BIGINT NOT NULL REFERENCES green_coffees(id),
  roast_profile      TEXT NOT NULL CHECK (roast_profile IN ('LIGHT','MEDIUM','DARK')),
  roast_date         DATE NOT NULL,
  green_weight_kg    NUMERIC(12,3) NOT NULL CHECK (green_weight_kg > 0),
  roasted_weight_kg  NUMERIC(12,3) NOT NULL CHECK (roasted_weight_kg > 0 AND roasted_weight_kg < green_weight_kg),
  weight_loss_pct    NUMERIC(5,2) GENERATED ALWAYS AS
                     (round((green_weight_kg - roasted_weight_kg) / green_weight_kg * 100, 2)) STORED,
  green_cost_per_kg  NUMERIC(14,4) NOT NULL CHECK (green_cost_per_kg >= 0),
  cost_per_kg        NUMERIC(14,4) NOT NULL CHECK (cost_per_kg >= 0),
  stock_kg           NUMERIC(12,3) NOT NULL CHECK (stock_kg >= 0),
  status             TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
  location           TEXT,
  roast_time_min     NUMERIC(5,1),
  end_temperature_c  NUMERIC(5,1),
  notes              TEXT,
  user_email         TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at          TIMESTAMPTZ,
  CHECK (status = 'OPEN' OR stock_kg = 0)
);

CREATE TABLE packing_batches (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              TEXT NOT NULL UNIQUE,
  roast_batch_id    BIGINT NOT NULL REFERENCES roast_batches(id),
  product_id        BIGINT NOT NULL REFERENCES products(id),
  packing_date      DATE NOT NULL,
  expiry_date       DATE NOT NULL,
  bag_count         INT NOT NULL CHECK (bag_count > 0),
  consumed_kg       NUMERIC(12,3) NOT NULL CHECK (consumed_kg > 0),
  coffee_unit_cost  NUMERIC(14,4) NOT NULL,
  bag_unit_cost     NUMERIC(14,4) NOT NULL,
  label_unit_cost   NUMERIC(14,4) NOT NULL,
  unit_cost         NUMERIC(14,4) GENERATED ALWAYS AS (coffee_unit_cost + bag_unit_cost + label_unit_cost) STORED,
  days_since_roast  INT NOT NULL CHECK (days_since_roast >= 0),
  user_email        TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (expiry_date > packing_date)
);

CREATE TABLE sales (
  id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  number               TEXT NOT NULL UNIQUE,
  customer_id          BIGINT NOT NULL REFERENCES customers(id),
  channel              TEXT NOT NULL CHECK (channel IN ('LOCAL','ONLINE','WHOLESALE')),
  delivery_type        TEXT NOT NULL CHECK (delivery_type IN ('PICKUP','LOCAL_DELIVERY','SHIPPING')),
  payment_method       TEXT NOT NULL CHECK (payment_method IN ('PIX','CASH','DEBIT_CARD','CREDIT_CARD','BANK_SLIP')),
  status               TEXT NOT NULL DEFAULT 'QUOTE'
                       CHECK (status IN ('QUOTE','CONFIRMED','SHIPPED','DELIVERED','CANCELLED')),
  quote_date           DATE NOT NULL,
  quote_valid_until    DATE,
  sale_date            DATE,
  products_amount      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (products_amount >= 0),
  discount_amount      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
  freight_amount       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (freight_amount >= 0),
  total_amount         NUMERIC(12,2) GENERATED ALWAYS AS (products_amount - discount_amount + freight_amount) STORED,
  total_weight_g       INT NOT NULL DEFAULT 0 CHECK (total_weight_g >= 0),
  box_count            INT NOT NULL DEFAULT 0 CHECK (box_count >= 0),
  products_cost        NUMERIC(12,2),
  boxes_cost           NUMERIC(12,2),
  payment_fee          NUMERIC(12,2),
  actual_freight_cost  NUMERIC(12,2),
  delivery_address     TEXT,
  carrier              TEXT,
  tracking_code        TEXT,
  notes                TEXT,
  user_email           TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at         TIMESTAMPTZ,
  shipped_at           TIMESTAMPTZ,
  delivered_at         TIMESTAMPTZ,
  cancelled_at         TIMESTAMPTZ,
  cancel_reason        TEXT,
  CHECK (discount_amount <= products_amount),
  CHECK (status NOT IN ('CONFIRMED','SHIPPED','DELIVERED') OR (sale_date IS NOT NULL AND products_cost IS NOT NULL)),
  CHECK (status <> 'CANCELLED' OR cancel_reason IS NOT NULL),
  CHECK (delivery_type = 'PICKUP' OR delivery_address IS NOT NULL),
  CHECK ( (channel = 'LOCAL'     AND delivery_type IN ('PICKUP','LOCAL_DELIVERY')
                                 AND payment_method IN ('PIX','CASH','DEBIT_CARD','CREDIT_CARD'))
       OR (channel = 'ONLINE'    AND delivery_type IN ('SHIPPING','LOCAL_DELIVERY')
                                 AND payment_method IN ('PIX','CREDIT_CARD'))
       OR (channel = 'WHOLESALE' AND delivery_type IN ('SHIPPING','LOCAL_DELIVERY')
                                 AND payment_method IN ('PIX','BANK_SLIP')) )
);

CREATE TABLE sale_items (
  id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sale_id             BIGINT NOT NULL REFERENCES sales(id),
  product_id          BIGINT NOT NULL REFERENCES products(id),
  quantity            INT NOT NULL CHECK (quantity > 0),
  unit_price          NUMERIC(12,2) NOT NULL CHECK (unit_price > 0),
  unit_cost_snapshot  NUMERIC(14,4),
  UNIQUE (sale_id, product_id)
);

CREATE TABLE sale_events (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sale_id      BIGINT NOT NULL REFERENCES sales(id),
  from_status  TEXT,
  to_status    TEXT NOT NULL,
  notes        TEXT,
  user_email   TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE stock_movements (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  movement_date      DATE NOT NULL,
  movement_type      TEXT NOT NULL CHECK (movement_type IN (
                       'PURCHASE_IN','PURCHASE_REVERSAL','HARVEST_IN','ROAST_OUT','ROAST_IN',
                       'PACKING_OUT','PACKING_IN','SALE_OUT','SALE_REVERSAL','INVENTORY_ADJUSTMENT')),
  green_coffee_id    BIGINT REFERENCES green_coffees(id),
  roast_batch_id     BIGINT REFERENCES roast_batches(id),
  packaging_item_id  BIGINT REFERENCES packaging_items(id),
  product_id         BIGINT REFERENCES products(id),
  quantity           NUMERIC(12,3) NOT NULL CHECK (quantity <> 0),
  unit_cost          NUMERIC(14,4) NOT NULL CHECK (unit_cost >= 0),
  total_value        NUMERIC(14,2) GENERATED ALWAYS AS (round(quantity * unit_cost, 2)) STORED,
  balance_after      NUMERIC(12,3) NOT NULL CHECK (balance_after >= 0),
  source_module      TEXT NOT NULL CHECK (source_module IN ('PURCHASES','PRODUCTION','SALES','INVENTORY')),
  source_id          BIGINT,
  reason             TEXT CHECK (reason IN ('COUNT','LOSS','DAMAGE','TASTING','EXPIRED','OPENING')),
  notes              TEXT,
  user_email         TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(green_coffee_id, roast_batch_id, packaging_item_id, product_id) = 1),
  CHECK ( (movement_type IN ('PURCHASE_IN','HARVEST_IN','ROAST_IN','PACKING_IN','SALE_REVERSAL') AND quantity > 0)
       OR (movement_type IN ('PURCHASE_REVERSAL','ROAST_OUT','PACKING_OUT','SALE_OUT') AND quantity < 0)
       OR (movement_type = 'INVENTORY_ADJUSTMENT' AND reason IS NOT NULL) ),
  CHECK ((packaging_item_id IS NULL AND product_id IS NULL) OR quantity = trunc(quantity))
);

CREATE TABLE financial_entries (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entry_type         TEXT NOT NULL CHECK (entry_type IN ('PAYABLE','RECEIVABLE')),
  category_id        BIGINT NOT NULL REFERENCES financial_categories(id),
  description        TEXT NOT NULL,
  amount             NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  accrual_date       DATE NOT NULL,
  due_date           DATE NOT NULL,
  installment        SMALLINT NOT NULL DEFAULT 1,
  installment_count  SMALLINT NOT NULL DEFAULT 1,
  status             TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SETTLED','CANCELLED')),
  settled_date       DATE,
  account_id         BIGINT REFERENCES financial_accounts(id),
  settlement_method  TEXT,
  is_reconciled      BOOLEAN NOT NULL DEFAULT FALSE,
  reconciled_date    DATE,
  source_module      TEXT NOT NULL CHECK (source_module IN ('PURCHASES','PRODUCTION','SALES','MANUAL')),
  source_id          BIGINT,
  supplier_id        BIGINT REFERENCES suppliers(id),
  customer_id        BIGINT REFERENCES customers(id),
  user_email         TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_by         TEXT,
  settled_at         TIMESTAMPTZ,
  cancelled_by       TEXT,
  cancelled_at       TIMESTAMPTZ,
  cancel_reason      TEXT,
  CHECK (installment BETWEEN 1 AND installment_count),
  CHECK (status <> 'SETTLED' OR (settled_date IS NOT NULL AND account_id IS NOT NULL)),
  CHECK (status = 'SETTLED' OR (settled_date IS NULL AND NOT is_reconciled)),
  CHECK (NOT is_reconciled OR reconciled_date IS NOT NULL),
  CHECK (source_module = 'MANUAL' OR source_id IS NOT NULL),
  CHECK (status <> 'CANCELLED' OR cancel_reason IS NOT NULL)
);

CREATE TABLE audit_log (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_name  TEXT NOT NULL,
  record_id   BIGINT,
  action      TEXT NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
  old_data    JSONB,
  new_data    JSONB,
  user_email  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE purchase_number_seq;
CREATE SEQUENCE harvest_number_seq;
CREATE SEQUENCE sale_number_seq;

CREATE INDEX ON stock_movements (green_coffee_id, movement_date) WHERE green_coffee_id IS NOT NULL;
CREATE INDEX ON stock_movements (roast_batch_id) WHERE roast_batch_id IS NOT NULL;
CREATE INDEX ON stock_movements (packaging_item_id, movement_date) WHERE packaging_item_id IS NOT NULL;
CREATE INDEX ON stock_movements (product_id, movement_date) WHERE product_id IS NOT NULL;
CREATE INDEX ON stock_movements (source_module, source_id);
CREATE INDEX ON sales (sale_date) WHERE status IN ('CONFIRMED','SHIPPED','DELIVERED');
CREATE INDEX ON sales (customer_id);
CREATE INDEX ON sales (status);
CREATE INDEX ON sale_items (product_id);
CREATE INDEX ON sale_events (sale_id);
CREATE INDEX ON purchases (supplier_id, status);
CREATE INDEX ON purchase_items (purchase_id);
CREATE INDEX ON roast_batches (green_coffee_id, roast_profile) WHERE status = 'OPEN';
CREATE INDEX ON packing_batches (product_id, packing_date);
CREATE INDEX ON financial_entries (status, due_date);
CREATE INDEX ON financial_entries (settled_date) WHERE status = 'SETTLED';
CREATE INDEX ON financial_entries (source_module, source_id);
CREATE INDEX ON financial_entries (customer_id) WHERE entry_type = 'RECEIVABLE';

CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  NEW.updated_by := coalesce(nullif(current_setting('app.user_email', true), ''), NEW.updated_by);
  RETURN NEW;
END;
$$;

DO $$
DECLARE
  target TEXT;
BEGIN
  FOREACH target IN ARRAY ARRAY['users','settings','suppliers','farms','green_coffees','packaging_items','products','customers']
  LOOP
    EXECUTE format('CREATE TRIGGER %I_touch_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()', target, target);
  END LOOP;
END;
$$;

DO $$
DECLARE
  target TEXT;
BEGIN
  FOR target IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', target);
  END LOOP;
END;
$$;
