-- Disposable PERSON vertical only. No Frappe migration or production install.
CREATE TABLE home_auth.binding (
    site_name VARCHAR(140) PRIMARY KEY,
    service_name VARCHAR(80) NOT NULL,
    partition_id VARCHAR(64) NOT NULL,
    site_database VARCHAR(64) NOT NULL,
    active TINYINT NOT NULL
) ENGINE=InnoDB;

CREATE TABLE home_auth.head (
    partition_id VARCHAR(64) PRIMARY KEY,
    incarnation VARCHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    digest VARCHAR(64) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE home_auth.events (
    partition_id VARCHAR(64) NOT NULL,
    incarnation VARCHAR(64) NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    request_sha VARCHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    digest VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    PRIMARY KEY (partition_id,incarnation,event_id),
    UNIQUE KEY one_revision (partition_id,incarnation,revision)
) ENGINE=InnoDB;

CREATE TABLE home_auth.activations (
    partition_id VARCHAR(64) NOT NULL,
    incarnation VARCHAR(64) NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    kind VARCHAR(8) NOT NULL,
    actor_person_id VARCHAR(140) NOT NULL,
    resource_id VARCHAR(140) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    action VARCHAR(16) NOT NULL,
    source_grant_id VARCHAR(140) NOT NULL,
    issuer_person_id VARCHAR(140) NOT NULL,
    PRIMARY KEY (partition_id,incarnation,event_id)
) ENGINE=InnoDB;

CREATE TABLE home_auth.dependency (
    partition_id VARCHAR(64) NOT NULL,
    grant_id VARCHAR(140) NOT NULL,
    current_state TINYINT NOT NULL,
    PRIMARY KEY (partition_id,grant_id)
) ENGINE=InnoDB;
