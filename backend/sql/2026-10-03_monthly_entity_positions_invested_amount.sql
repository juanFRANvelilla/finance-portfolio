-- Renombra cumulative_invested → invested_amount; LIQUID debe llevar NULL.
BEGIN;

ALTER TABLE public.monthly_entity_positions
    RENAME COLUMN cumulative_invested TO invested_amount;

ALTER TABLE public.monthly_entity_positions
    ALTER COLUMN invested_amount DROP NOT NULL;

ALTER TABLE public.monthly_entity_positions
    ALTER COLUMN invested_amount DROP DEFAULT;

UPDATE public.monthly_entity_positions AS mep
SET invested_amount = NULL
FROM public.entities AS e
WHERE e.id = mep.entity_id
  AND e.entity_type = 'LIQUID';

UPDATE public.monthly_entity_positions AS mep
SET invested_amount = COALESCE(mep.invested_amount, 0)
FROM public.entities AS e
WHERE e.id = mep.entity_id
  AND e.entity_type = 'HYBRID';

CREATE OR REPLACE FUNCTION public.enforce_monthly_entity_position_invested()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    et public.entity_type;
BEGIN
    SELECT entity_type INTO et FROM public.entities WHERE id = NEW.entity_id;
    IF et = 'LIQUID' THEN
        IF NEW.invested_amount IS NOT NULL THEN
            RAISE EXCEPTION 'monthly_entity_positions: entidad LIQUID % requiere invested_amount NULL', NEW.entity_id;
        END IF;
    ELSIF et = 'HYBRID' THEN
        IF NEW.invested_amount IS NULL THEN
            RAISE EXCEPTION 'monthly_entity_positions: entidad HYBRID % requiere invested_amount NOT NULL', NEW.entity_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_monthly_entity_positions_invested ON public.monthly_entity_positions;

CREATE TRIGGER trg_monthly_entity_positions_invested
    BEFORE INSERT OR UPDATE OF invested_amount, entity_id
    ON public.monthly_entity_positions
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_monthly_entity_position_invested();

COMMIT;
