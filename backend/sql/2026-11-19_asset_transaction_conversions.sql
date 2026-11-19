-- Migración para registrar detalles de conversión multidivisa (USDT -> EUR, etc.)
CREATE TABLE IF NOT EXISTS public.asset_transaction_conversions (
    transaction_id UUID PRIMARY KEY REFERENCES public.asset_transactions(id) ON DELETE CASCADE,
    quote_currency VARCHAR(10) NOT NULL,
    original_invested_amount NUMERIC(16, 8) NOT NULL,
    original_execution_price NUMERIC(16, 8) NOT NULL,
    fx_rate NUMERIC(12, 6) NOT NULL,
    bridge_exchange_trade_id VARCHAR(100) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
);
