-- Disposable Task 1 schema. Each writer epoch is bound to exactly one DB principal
-- in witness.writer_principals; recovery activates the next unused principal and
-- retires (locks and disconnects) every previous one for that partition.
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

-- Recovery history includes incarnations that never published an event.
CREATE TABLE witness.incarnations (
    partition_id VARCHAR(64) NOT NULL,
    incarnation VARCHAR(64) NOT NULL,
    PRIMARY KEY (incarnation)
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

-- Operator-provisioned writer credentials, one per epoch. A principal is used for
-- at most one epoch of one partition and never returns from RETIRED.
CREATE TABLE witness.writer_principals (
    partition_id VARCHAR(64) NOT NULL,
    epoch INT NOT NULL,
    principal VARCHAR(160) NOT NULL,
    state VARCHAR(8) NOT NULL,
    PRIMARY KEY (partition_id, epoch),
    UNIQUE KEY one_principal (principal),
    CHECK (state IN ('UNUSED','ACTIVE','RETIRED'))
) ENGINE=InnoDB;

DELIMITER //

-- The calling session's own principal must be the ACTIVE one for the head epoch.
-- USER() is the authenticated client even inside a SQL SECURITY DEFINER routine.
CREATE FUNCTION witness._caller_is_writer(p_partition VARCHAR(64), p_epoch INT)
RETURNS TINYINT READS SQL DATA SQL SECURITY DEFINER
RETURN EXISTS (
    SELECT 1 FROM witness.writer_principals
     WHERE partition_id=p_partition AND epoch=p_epoch
       AND principal=USER() AND state='ACTIVE'
)//

CREATE PROCEDURE witness.prepare_event(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
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
    IF v_incarnation IS NULL OR v_incarnation <> p_incarnation
       OR NOT witness._caller_is_writer(p_partition, v_epoch) THEN
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

CREATE PROCEDURE witness.commit_event(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64),
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
    IF v_incarnation IS NULL OR v_incarnation <> p_incarnation
       OR NOT witness._caller_is_writer(p_partition, v_epoch) THEN
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

-- Not granted to any principal; only recover_partition calls it, after its commit.
-- Locks every retired writer account of the partition, then disconnects its sessions.
CREATE PROCEDURE witness._retire_writers(IN p_partition VARCHAR(64))
SQL SECURITY DEFINER
BEGIN
    DECLARE v_done INT DEFAULT 0;
    DECLARE v_principal VARCHAR(160);
    DECLARE v_id BIGINT;
    DECLARE retired CURSOR FOR
        SELECT principal FROM witness.writer_principals
         WHERE partition_id=p_partition AND state='RETIRED';
    DECLARE sessions CURSOR FOR
        SELECT p.ID FROM information_schema.PROCESSLIST p
          JOIN witness.writer_principals w
            ON w.principal=CONCAT(p.USER,'@',SUBSTRING_INDEX(p.HOST,':',1))
         WHERE w.partition_id=p_partition AND w.state='RETIRED'
           AND p.ID<>CONNECTION_ID();
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done=1;
    -- A session that ended between listing and KILL is already retired.
    DECLARE CONTINUE HANDLER FOR 1094 BEGIN END;
    OPEN retired;
    lock_accounts: LOOP
        FETCH retired INTO v_principal;
        IF v_done THEN LEAVE lock_accounts; END IF;
        SET @kap2_retire_writer = CONCAT(
            'ALTER USER ', QUOTE(SUBSTRING_INDEX(v_principal,'@',1)), '@',
            QUOTE(SUBSTRING_INDEX(v_principal,'@',-1)), ' ACCOUNT LOCK');
        PREPARE kap2_retire_writer FROM @kap2_retire_writer;
        EXECUTE kap2_retire_writer;
        DEALLOCATE PREPARE kap2_retire_writer;
    END LOOP;
    CLOSE retired;
    SET v_done=0;
    OPEN sessions;
    kill_sessions: LOOP
        FETCH sessions INTO v_id;
        IF v_done THEN LEAVE kill_sessions; END IF;
        KILL CONNECTION v_id;
    END LOOP;
    CLOSE sessions;
END//

-- p_next_auth is the mysql_native_password stored hash of a credential the gateway
-- minted for this recovery only; the plaintext never reaches the witness.
CREATE PROCEDURE witness.recover_partition(
    IN p_partition VARCHAR(64), IN p_new_incarnation VARCHAR(64),
    IN p_next_principal VARCHAR(160), IN p_next_auth VARCHAR(41)
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_old VARCHAR(64);
    DECLARE v_epoch INT;
    DECLARE v_next_state VARCHAR(8);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    IF p_new_incarnation IS NULL OR p_new_incarnation NOT REGEXP '^[0-9a-f]{64}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid incarnation';
    END IF;
    IF p_next_auth IS NULL OR p_next_auth NOT REGEXP BINARY '^\\*[0-9A-F]{40}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid writer credential hash';
    END IF;
    START TRANSACTION;
    SELECT incarnation, writer_epoch INTO v_old, v_epoch FROM witness.head
      WHERE partition_id=p_partition FOR UPDATE;
    IF v_old IS NULL OR v_old=p_new_incarnation OR EXISTS (
        SELECT 1 FROM witness.incarnations
          WHERE incarnation=p_new_incarnation
    ) OR EXISTS (
        SELECT 1 FROM witness.events
          WHERE incarnation=p_new_incarnation
    ) OR EXISTS (
        SELECT 1 FROM witness.head WHERE incarnation=p_new_incarnation
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='missing partition or reused incarnation';
    END IF;
    -- The next epoch must use a provisioned principal that has never been used.
    SET v_next_state = (SELECT state FROM witness.writer_principals
                         WHERE partition_id=p_partition AND epoch=v_epoch+1
                           AND principal=p_next_principal);
    IF v_next_state IS NULL OR v_next_state<>'UNUSED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='next writer principal unavailable';
    END IF;
    INSERT IGNORE INTO witness.incarnations VALUES (p_partition,v_old);
    INSERT INTO witness.incarnations VALUES (p_partition,p_new_incarnation);
    UPDATE witness.writer_principals SET state='RETIRED'
     WHERE partition_id=p_partition AND state='ACTIVE';
    UPDATE witness.writer_principals SET state='ACTIVE'
     WHERE partition_id=p_partition AND epoch=v_epoch+1;
    UPDATE witness.head SET incarnation=p_new_incarnation,revision=0,
      writer_epoch=v_epoch+1,publisher_epoch=v_epoch+1,state='COMMITTED',event_id=NULL,
      digest='DENY_ALL',ready_hint=0 WHERE partition_id=p_partition;
    COMMIT;
    -- Account DDL commits implicitly, so it follows the authority transaction.
    -- A failure here leaves the gateway closed; the next recovery moves on again.
    SET @kap2_activate_writer = CONCAT(
        'ALTER USER ', QUOTE(SUBSTRING_INDEX(p_next_principal,'@',1)), '@',
        QUOTE(SUBSTRING_INDEX(p_next_principal,'@',-1)),
        ' IDENTIFIED BY PASSWORD ', QUOTE(p_next_auth), ' ACCOUNT UNLOCK');
    PREPARE kap2_activate_writer FROM @kap2_activate_writer;
    EXECUTE kap2_activate_writer;
    DEALLOCATE PREPARE kap2_activate_writer;
    SET @kap2_activate_writer = NULL;
    CALL witness._retire_writers(p_partition);
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
