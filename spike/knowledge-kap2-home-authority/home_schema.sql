-- Disposable private Home Knowledge authority schema; not a Frappe migration.
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
    expected_revision BIGINT NOT NULL,
    revision BIGINT NOT NULL,
    digest VARCHAR(64) NOT NULL,
    request_sha VARCHAR(64) NOT NULL,
    PRIMARY KEY (partition_id,incarnation,event_id),
    UNIQUE KEY one_revision (partition_id,incarnation,revision)
) ENGINE=InnoDB;

CREATE TABLE home_auth.activations (
    partition_id VARCHAR(64) NOT NULL,
    incarnation VARCHAR(64) NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    kind VARCHAR(8) NOT NULL,
    actor_person_id VARCHAR(140) NOT NULL,
    resource_type VARCHAR(8) NOT NULL,
    resource_id VARCHAR(140) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    actions VARCHAR(80) NOT NULL,
    source_grant_id VARCHAR(140) NOT NULL,
    issuer_person_id VARCHAR(140) NOT NULL,
    revision BIGINT NOT NULL,
    PRIMARY KEY (partition_id,incarnation,event_id)
) ENGINE=InnoDB;

DELIMITER //
CREATE PROCEDURE home_auth.read_head(IN p_partition VARCHAR(64))
SQL SECURITY DEFINER
BEGIN
    START TRANSACTION;
    SELECT incarnation,revision,digest FROM home_auth.head
      WHERE partition_id=p_partition FOR UPDATE;
    COMMIT;
END//

CREATE PROCEDURE home_auth.apply_event(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_expected BIGINT,
    IN p_digest VARCHAR(64), IN p_request_sha VARCHAR(64),
    IN p_kind VARCHAR(8), IN p_actor VARCHAR(140),
    IN p_type VARCHAR(8), IN p_resource VARCHAR(140),
    IN p_domain VARCHAR(32), IN p_actions VARCHAR(80),
    IN p_source VARCHAR(140), IN p_issuer VARCHAR(140),
    IN p_epoch INT
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_incarnation VARCHAR(64);
    DECLARE v_revision BIGINT;
    DECLARE v_count INT;
    DECLARE v_expected BIGINT;
    DECLARE v_digest VARCHAR(64);
    DECLARE v_sha VARCHAR(64);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    SELECT incarnation,revision INTO v_incarnation,v_revision
      FROM home_auth.head WHERE partition_id=p_partition FOR UPDATE;
    IF v_incarnation IS NULL OR v_incarnation<>p_incarnation OR p_epoch<>2 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='obsolete Home incarnation or principal';
    END IF;
    SELECT COUNT(*) INTO v_count FROM home_auth.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
    IF v_count=1 THEN
        SELECT expected_revision,digest,request_sha INTO v_expected,v_digest,v_sha
          FROM home_auth.events WHERE partition_id=p_partition
          AND incarnation=p_incarnation AND event_id=p_event;
        IF v_expected<>p_expected OR v_digest<>p_digest OR v_sha<>p_request_sha THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='conflicting Home event retry';
        END IF;
    ELSE
        IF v_revision<>p_expected OR p_kind NOT IN ('GRANT','SELF')
           OR p_type NOT IN ('PERSON','CIRCLE')
           OR (p_kind='SELF' AND (p_type<>'PERSON' OR p_actor<>p_resource
               OR p_issuer<>p_actor OR p_source<>''))
           OR (p_kind='GRANT' AND (p_source='' OR
               (p_type='PERSON' AND p_issuer<>p_resource))) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='illegal Home event transition';
        END IF;
        INSERT INTO home_auth.events VALUES
          (p_partition,p_incarnation,p_event,p_expected,p_expected+1,p_digest,p_request_sha);
        INSERT INTO home_auth.activations VALUES
          (p_partition,p_incarnation,p_event,p_kind,p_actor,p_type,p_resource,
           p_domain,p_actions,p_source,p_issuer,p_expected+1);
        UPDATE home_auth.head SET revision=p_expected+1,digest=p_digest
          WHERE partition_id=p_partition;
    END IF;
    COMMIT;
    SELECT revision,digest FROM home_auth.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
END//
DELIMITER ;
