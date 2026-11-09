-- El mismo nombre puede existir en otra entidad (NVIDIA de MyInvestor y de Trade Republic).
ALTER TABLE public.asset_types DROP CONSTRAINT IF EXISTS uq_asset_type_name;

ALTER TABLE public.asset_types
    ADD CONSTRAINT uq_asset_type_name_entity UNIQUE (name, entity_id);
