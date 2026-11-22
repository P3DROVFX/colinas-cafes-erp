INSERT INTO settings (key, value, value_type, description) VALUES
  ('roaster_capacity_kg',         '15',         'DECIMAL', 'Capacidade máxima de café verde por batelada (kg)'),
  ('roast_min_kg',                '1',          'DECIMAL', 'Quantidade mínima de café verde por batelada (kg)'),
  ('weight_loss_warn_min_pct',    '10',         'DECIMAL', 'Quebra mínima sem alerta (%)'),
  ('weight_loss_warn_max_pct',    '25',         'DECIMAL', 'Quebra máxima sem alerta (%)'),
  ('weight_loss_block_min_pct',   '5',          'DECIMAL', 'Quebra abaixo deste valor é bloqueada (%)'),
  ('weight_loss_block_max_pct',   '35',         'DECIMAL', 'Quebra acima deste valor é bloqueada (%)'),
  ('roast_batch_alert_days',      '15',         'INT',     'Dias sem envase para alertar frescor do lote torrado'),
  ('product_shelf_life_months',   '12',         'INT',     'Validade do produto envasado (meses)'),
  ('default_shipping_box_id',     NULL,         'INT',     'Caixa de envio padrão usada no cálculo de caixas'),
  ('quote_validity_days',         '7',          'INT',     'Validade dos orçamentos (dias)'),
  ('max_discount_pct',            '10',         'DECIMAL', 'Desconto máximo sem aprovação gerencial (%)'),
  ('wholesale_min_order_kg',      '5',          'DECIMAL', 'Peso mínimo do pedido de atacado (kg)'),
  ('wholesale_default_term_days', '28',         'INT',     'Prazo de pagamento padrão para clientes de atacado (dias)'),
  ('overdue_tolerance_days',      '5',          'INT',     'Atraso tolerado antes de bloquear venda a prazo (dias)'),
  ('credit_card_fee_pct',         '3.5',        'DECIMAL', 'Taxa do cartão de crédito (%)'),
  ('credit_card_term_days',       '30',         'INT',     'Prazo de recebimento do cartão de crédito (dias)'),
  ('debit_card_fee_pct',          '1.5',        'DECIMAL', 'Taxa do cartão de débito (%)'),
  ('debit_card_term_days',        '1',          'INT',     'Prazo de recebimento do cartão de débito (dias)'),
  ('due_alert_days',              '7',          'INT',     'Antecedência para alertar títulos a vencer (dias)'),
  ('packaging_lead_time_days',    '10',         'INT',     'Prazo de reposição de embalagens (dias)'),
  ('safety_stock_days',           '7',          'INT',     'Estoque de segurança no ponto de pedido (dias)'),
  ('operation_start_date',        '2026-06-01', 'DATE',    'Data de início da operação no sistema');

INSERT INTO financial_categories (name, entry_type, dre_group, is_system) VALUES
  ('Venda de cafés',                       'RECEIVABLE', 'REVENUE',           TRUE),
  ('Outras receitas',                      'RECEIVABLE', 'OTHER_REVENUE',     TRUE),
  ('Reembolso a clientes',                 'PAYABLE',    'REFUND',            TRUE),
  ('Compra de café verde',                 'PAYABLE',    'INVENTORY',         TRUE),
  ('Compra de embalagens',                 'PAYABLE',    'INVENTORY',         TRUE),
  ('Custos de colheita e beneficiamento',  'PAYABLE',    'INVENTORY',         TRUE),
  ('Taxas de meios de pagamento',          'PAYABLE',    'SELLING_COST',      TRUE),
  ('Fretes sobre vendas',                  'PAYABLE',    'SELLING_COST',      TRUE),
  ('Gás do torrador',                      'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Energia elétrica',                     'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Aluguel',                              'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Salários e pró-labore',                'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Marketing',                            'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Plataforma de e-commerce',             'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Manutenção de equipamentos',           'PAYABLE',    'OPERATING_EXPENSE', FALSE),
  ('Outras despesas',                      'PAYABLE',    'OPERATING_EXPENSE', FALSE);

INSERT INTO financial_accounts (name, kind, opening_balance, opening_date, is_system) VALUES
  ('Caixa da loja',     'CASH', 0, DATE '2026-06-01', TRUE),
  ('Banco - conta PJ',  'BANK', 0, DATE '2026-06-01', TRUE);

INSERT INTO customers (name, person_type, segment) VALUES
  ('Consumidor Final', 'PF', 'CONSUMER');
