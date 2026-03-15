CREATE TABLE IF NOT EXISTS bom_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'csv',
    parser_key TEXT NOT NULL DEFAULT 'nlc',
    manufacturer TEXT NOT NULL DEFAULT 'Nonlinearcircuits',
    module_name TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    notes TEXT,
    promoted_project_id INTEGER,
    FOREIGN KEY(promoted_project_id) REFERENCES modules(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_bom_sources_hash ON bom_sources(file_hash);
CREATE INDEX IF NOT EXISTS idx_bom_sources_parser ON bom_sources(parser_key);

CREATE TABLE IF NOT EXISTS raw_bom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_source_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    raw_description TEXT NOT NULL,
    raw_qty TEXT NOT NULL DEFAULT '',
    raw_reference TEXT,
    raw_supplier_pn TEXT,
    raw_notes TEXT,
    FOREIGN KEY(bom_source_id) REFERENCES bom_sources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_raw_bom_items_source ON raw_bom_items(bom_source_id);

CREATE TABLE IF NOT EXISTS normalized_bom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_source_id INTEGER NOT NULL,
    raw_item_id INTEGER NOT NULL,
    component_type TEXT,
    normalized_value TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK(qty > 0),
    package_hint TEXT,
    reference TEXT,
    tayda_pn TEXT,
    mouser_pn TEXT,
    part_id INTEGER,
    match_confidence REAL,
    match_status TEXT NOT NULL DEFAULT 'unmatched',
    is_verified INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    FOREIGN KEY(bom_source_id) REFERENCES bom_sources(id) ON DELETE CASCADE,
    FOREIGN KEY(raw_item_id) REFERENCES raw_bom_items(id) ON DELETE CASCADE,
    FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_normalized_bom_items_source ON normalized_bom_items(bom_source_id);
CREATE INDEX IF NOT EXISTS idx_normalized_bom_items_part ON normalized_bom_items(part_id);
CREATE INDEX IF NOT EXISTS idx_normalized_bom_items_status ON normalized_bom_items(match_status);
