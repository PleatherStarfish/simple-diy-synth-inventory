-- Add default_package to the inventory summary view.
DROP VIEW IF EXISTS part_inventory_summary;

CREATE VIEW IF NOT EXISTS part_inventory_summary AS
SELECT
    p.id AS part_id,
    p.name AS name,
    p.category AS category,
    p.default_package AS default_package,
    p.supplier_sku AS supplier_sku,
    p.qty AS total_qty,
    COALESCE(sc.name || ' / ' || ss.label, '') AS locations,
    p.notes AS notes
FROM parts p
LEFT JOIN storage_slots ss ON ss.id = p.slot_id
LEFT JOIN storage_containers sc ON sc.id = ss.container_id;
