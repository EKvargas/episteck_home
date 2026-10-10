-- Disposable Task 1 schema. The two epoch entry points model distinct DB principals.
CREATE TABLE witness.head (
    partition_id VARCHAR(64) PRIMARY KEY,
    incarnation VARCHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    writer_epoch INT NOT NULL,
    publisher_epoch INT NOT NULL,
    state VARCHAR(16) NOT NULL,
    event_id VARCHAR(64) NULL,
    digest VARCHAR(64) NOT NULL,
    ready_hint TINYINT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE witness.events (
    partition_id VARCHAR(64) NOT NULL,
    incarnation VARCHAR(64) NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    expected_revision BIGINT NOT NULL,
    revision BIGINT NOT NULL,
    proposed_digest VARCHAR(64) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    PRIMARY KEY (partition_id, incarnation, event_id),
    UNIQUE KEY one_revision (partition_id, incarnation, revision)
) ENGINE=InnoDB;

DELIMITER //

CREATE PROCEDURE witness._prepare(
    IN p_epoch INT, IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_expected BIGINT, IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_incarnation VARCHAR(64);
    DECLARE v_epoch INT;
    DECLARE v_state VARCHAR(16);
    DECLARE v_revision BIGINT;
    DECLARE v_head_event VARCHAR(64);
    DECLARE v_count INT;
    DECLARE v_expected BIGINT;
    DECLARE v_digest VARCHAR(64);
    DECLARE v_outcome VARCHAR(16);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    SELECT incarnation, writer_epoch, state, revision, event_id
      INTO v_incarnation, v_epoch, v_state, v_revision, v_head_event
      FROM witness.head WHERE partition_id=p_partition FOR UPDATE;
    IF v_incarnation IS NULL OR v_incarnation <> p_incarnation OR v_epoch <> p_epoch THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='obsolete incarnation or principal';
    END IF;
    SELECT COUNT(*) INTO v_count FROM witness.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
    IF v_count = 1 THEN
        SELECT expected_revision, proposed_digest, outcome
          INTO v_expected, v_digest, v_outcome FROM witness.events
          WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
        IF v_expected <> p_expected OR v_digest <> p_digest OR
           (v_outcome='PENDING' AND (v_state<>'PENDING' OR v_head_event<>p_event)) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='conflicting event retry';
        END IF;
    ELSE
        IF v_state <> 'COMMITTED' OR v_revision <> p_expected THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='illegal prepare transition';
        END IF;
        INSERT INTO witness.events VALUES
          (p_partition,p_incarnation,p_event,p_expected,p_expected+1,p_digest,'PENDING');
        UPDATE witness.head SET revision=p_expected+1,state='PENDING',event_id=p_event,
          ready_hint=0 WHERE partition_id=p_partition;
    END IF;
    COMMIT;
END//

CREATE PROCEDURE witness._commit(
    IN p_epoch INT, IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_incarnation VARCHAR(64);
    DECLARE v_epoch INT;
    DECLARE v_state VARCHAR(16);
    DECLARE v_head_event VARCHAR(64);
    DECLARE v_count INT;
    DECLARE v_digest VARCHAR(64);
    DECLARE v_outcome VARCHAR(16);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    SELECT incarnation, writer_epoch, state, event_id
      INTO v_incarnation, v_epoch, v_state, v_head_event
      FROM witness.head WHERE partition_id=p_partition FOR UPDATE;
    IF v_incarnation IS NULL OR v_incarnation <> p_incarnation OR v_epoch <> p_epoch THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='obsolete incarnation or principal';
    END IF;
    SELECT COUNT(*) INTO v_count FROM witness.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
    IF v_count <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='unknown event';
    END IF;
    SELECT proposed_digest, outcome INTO v_digest, v_outcome FROM witness.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
    IF v_digest <> p_digest THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='conflicting commit retry';
    END IF;
    IF v_outcome = 'PENDING' THEN
        IF v_state <> 'PENDING' OR v_head_event <> p_event THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='illegal commit transition';
        END IF;
        UPDATE witness.events SET outcome='COMMITTED'
          WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
        UPDATE witness.head SET state='COMMITTED',digest=p_digest,ready_hint=0
          WHERE partition_id=p_partition;
    END IF;
    COMMIT;
END//

CREATE PROCEDURE witness.prepare_e1(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_expected BIGINT, IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN CALL witness._prepare(1,p_partition,p_incarnation,p_event,p_expected,p_digest); END//

CREATE PROCEDURE witness.commit_e1(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN CALL witness._commit(1,p_partition,p_incarnation,p_event,p_digest); END//

CREATE PROCEDURE witness.prepare_e2(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_expected BIGINT, IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN CALL witness._prepare(2,p_partition,p_incarnation,p_event,p_expected,p_digest); END//

CREATE PROCEDURE witness.commit_e2(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
    IN p_event VARCHAR(64), IN p_digest VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN CALL witness._commit(2,p_partition,p_incarnation,p_event,p_digest); END//

CREATE PROCEDURE witness.recover_e2(
    IN p_partition VARCHAR(64), IN p_new_incarnation VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_old VARCHAR(64);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    IF p_new_incarnation NOT REGEXP '^[0-9a-f]{64}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid incarnation';
    END IF;
    START TRANSACTION;
    SELECT incarnation INTO v_old FROM witness.head
      WHERE partition_id=p_partition FOR UPDATE;
    IF v_old IS NULL OR v_old=p_new_incarnation THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='missing partition or reused incarnation';
    END IF;
    UPDATE witness.head SET incarnation=p_new_incarnation,revision=0,
      writer_epoch=2,publisher_epoch=2,state='COMMITTED',event_id=NULL,
      digest='DENY_ALL',ready_hint=0 WHERE partition_id=p_partition;
    COMMIT;
END//

CREATE PROCEDURE witness.read_current(IN p_partition VARCHAR(64))
SQL SECURITY DEFINER
BEGIN
    START TRANSACTION;
    SELECT incarnation,revision,writer_epoch,publisher_epoch,state,event_id,digest
      FROM witness.head WHERE partition_id=p_partition FOR UPDATE;
    COMMIT;
END//

CREATE PROCEDURE witness.read_event(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64), IN p_event VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN
    START TRANSACTION;
    SELECT outcome,revision,proposed_digest FROM witness.events
      WHERE partition_id=p_partition AND incarnation=p_incarnation AND event_id=p_event;
    COMMIT;
END//

DELIMITER ;
