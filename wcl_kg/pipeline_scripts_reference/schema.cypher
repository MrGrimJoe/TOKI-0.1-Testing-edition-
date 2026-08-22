// ============================================================
// Windows Command Library -- Kuzu graph schema
// ============================================================

// ---- Node tables ----
CREATE NODE TABLE Command(
    id STRING,
    name STRING,
    tool STRING,
    category STRING,
    description STRING,
    syntax STRING,
    danger_level STRING,
    requires_admin BOOLEAN,
    requires_confirmation BOOLEAN,
    platform STRING,
    availability STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE Category(
    name STRING,
    PRIMARY KEY (name)
);

CREATE NODE TABLE Module(
    name STRING,
    PRIMARY KEY (name)
);

CREATE NODE TABLE Intent(
    name STRING,
    PRIMARY KEY (name)
);

CREATE NODE TABLE Alias(
    text STRING,
    PRIMARY KEY (text)
);

CREATE NODE TABLE VariableType(
    name STRING,
    description STRING,
    value_type STRING,
    PRIMARY KEY (name)
);

CREATE NODE TABLE Example(
    id STRING,
    user_input STRING,
    resolved_command STRING,
    PRIMARY KEY (id)
);

// ---- Relationship tables ----
CREATE REL TABLE InCategory(FROM Command TO Category);
CREATE REL TABLE RequiresModule(FROM Command TO Module);
CREATE REL TABLE HasIntent(FROM Command TO Intent, position INT64);
CREATE REL TABLE HasAlias(FROM Command TO Alias, position INT64);
CREATE REL TABLE HasVariable(FROM Command TO VariableType, position INT64, example_value STRING);
CREATE REL TABLE HasExample(FROM Command TO Example);
CREATE REL TABLE SynonymOf(FROM Intent TO Intent);
