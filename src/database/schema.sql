-- Table 1.:papers : stores metadata for the selected papers


CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source TEXT NOT NULL,
    external_id TEXT NOT NULL,

    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    abstract TEXT,

    paper_url TEXT,
    pdf_url TEXT,

    last_analyzed_at TEXT,

    analysis_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            analysis_status IN (
                'pending',
                'completed',
                'partial',
                'failed'
            )
        ),

    UNIQUE (source, external_id)
);


-- Table.: resources : stores unique resources belonging to papers

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    paper_id INTEGER NOT NULL,

    url TEXT NOT NULL,

    resource_type TEXT NOT NULL
        CHECK (
            resource_type IN (
                'Code',
                'Dataset',
                'Documentation',
                'Supplementary material',
                'Unknown'
            )
        ),

    accessibility_status TEXT NOT NULL
        CHECK (
            accessibility_status IN (
                'Accessible',
                'Inaccessible',
                'Inconclusive'
            )
        ),

    http_status INTEGER,
    error_message TEXT,
    checked_at TEXT,

    FOREIGN KEY (paper_id)
        REFERENCES papers(id)
        ON DELETE CASCADE,

    UNIQUE (paper_id, url)
);