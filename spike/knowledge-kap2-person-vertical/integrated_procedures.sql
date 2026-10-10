-- Disposable, per-site definer procedures. Installer replaces __SITE_DB__ only
-- after checking the 16-hex Frappe database name. Never a production migration.
DELIMITER //

CREATE PROCEDURE home_auth._assert_person_lane(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64), IN p_revision BIGINT
) SQL SECURITY DEFINER
BEGIN
    DECLARE v_incarnation VARCHAR(64) DEFAULT NULL;
    DECLARE v_revision BIGINT DEFAULT NULL;
    IF IS_USED_LOCK(CONCAT('kap2_person_', LEFT(SHA2(p_partition, 256), 40)))
       IS NULL OR IS_USED_LOCK(CONCAT('kap2_person_', LEFT(SHA2(p_partition, 256), 40)))
       <> CONNECTION_ID() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_LANE_REQUIRED';
    END IF;
    SELECT incarnation, revision INTO v_incarnation, v_revision
      FROM home_auth.head WHERE partition_id=p_partition;
    IF v_incarnation IS NULL OR v_incarnation<>p_incarnation
       OR v_revision<>p_revision THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_STALE_HEAD';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM home_auth.binding
                   WHERE partition_id=p_partition AND site_database='__SITE_DB__'
                   AND active=1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_UNBOUND_PARTITION';
    END IF;
END//

CREATE PROCEDURE home_auth.stage_person_mutation(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64), IN p_revision BIGINT,
    IN p_event VARCHAR(64), IN p_kind VARCHAR(32), IN p_source VARCHAR(140),
    IN p_actor VARCHAR(140), IN p_target VARCHAR(140), IN p_domain VARCHAR(32),
    IN p_action VARCHAR(16), IN p_issuer VARCHAR(140), IN p_user VARCHAR(140)
) SQL SECURITY DEFINER
BEGIN
    CALL home_auth._assert_person_lane(p_partition,p_incarnation,p_revision);
    IF p_event IS NULL OR p_event='' OR p_issuer IS NULL OR p_issuer='' OR
       (SELECT COUNT(*) FROM `__SITE_DB__`.`tabPerson`
        WHERE name=p_issuer AND linked_user=p_user)<>1 OR
       NOT EXISTS (SELECT 1 FROM `__SITE_DB__`.`tabUser`
                   WHERE name=p_user AND enabled=1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_ISSUER_REQUIRED';
    END IF;
    IF p_kind='GRANT' THEN
        IF p_target<>p_issuer OR NOT EXISTS (
            SELECT 1 FROM `__SITE_DB__`.`tabConsent Grant`
             WHERE name=p_source AND actor_person=p_actor AND subject_person=p_target
               AND granted_by=p_issuer AND domain=p_domain AND state='ACTIVE'
               AND FIND_IN_SET(p_action,REPLACE(REPLACE(actions,CHAR(10),','),' ',''))>0
        ) OR NOT EXISTS (SELECT 1 FROM home_auth.dependency
                         WHERE partition_id=p_partition AND grant_id=p_source
                         AND current_state=1) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_GRANT_REQUIRED';
        END IF;
        INSERT INTO home_auth.activations VALUES
            (p_partition,p_incarnation,p_event,'GRANT',p_actor,p_target,
             p_domain,p_action,p_source,p_issuer);
    ELSEIF p_kind='SELF' THEN
        IF p_actor<>p_issuer OR p_target<>p_issuer OR p_source<>'' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_SELF_REQUIRED';
        END IF;
        INSERT INTO home_auth.activations VALUES
            (p_partition,p_incarnation,p_event,'SELF',p_actor,p_target,
             p_domain,p_action,'',p_issuer);
    ELSEIF p_kind='REVOKE' OR p_kind='DEPENDENCY_OFF' THEN
        IF NOT EXISTS (SELECT 1 FROM `__SITE_DB__`.`tabConsent Grant`
                       WHERE name=p_source AND subject_person=p_issuer) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_GRANT_ISSUER_REQUIRED';
        END IF;
        IF p_kind='REVOKE' THEN
            UPDATE `__SITE_DB__`.`tabConsent Grant` SET state='REVOKED'
             WHERE name=p_source;
        ELSE
            UPDATE home_auth.dependency SET current_state=0
             WHERE partition_id=p_partition AND grant_id=p_source;
            IF ROW_COUNT()<>1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_DEPENDENCY_REQUIRED';
            END IF;
        END IF;
    ELSEIF p_kind='DISABLE_ISSUER' THEN
        IF p_source<>p_user THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_USER_REQUIRED';
        END IF;
        UPDATE `__SITE_DB__`.`tabUser` SET enabled=0 WHERE name=p_user;
        IF ROW_COUNT()<>1 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_USER_REQUIRED';
        END IF;
    ELSEIF p_kind='UNLINK_ISSUER' THEN
        IF p_source<>p_issuer THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_PERSON_REQUIRED';
        END IF;
        UPDATE `__SITE_DB__`.`tabPerson` SET linked_user=NULL WHERE name=p_issuer;
        IF ROW_COUNT()<>1 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_PERSON_REQUIRED';
        END IF;
    ELSE
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_KIND_REQUIRED';
    END IF;
END//

CREATE PROCEDURE home_auth.record_person_event(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64), IN p_revision BIGINT,
    IN p_event VARCHAR(64), IN p_request_sha VARCHAR(64),
    IN p_digest VARCHAR(64), IN p_kind VARCHAR(32)
) SQL SECURITY DEFINER
BEGIN
    CALL home_auth._assert_person_lane(p_partition,p_incarnation,p_revision);
    IF p_event IS NULL OR p_event='' OR CHAR_LENGTH(p_request_sha)<>64 OR
       (CHAR_LENGTH(p_digest)<>64 AND p_digest<>'DENY_ALL') OR
       p_kind NOT IN ('GRANT','SELF','REVOKE','DEPENDENCY_OFF',
                      'DISABLE_ISSUER','UNLINK_ISSUER') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_EVENT_REQUIRED';
    END IF;
    IF p_kind IN ('GRANT','SELF') AND NOT EXISTS (
        SELECT 1 FROM home_auth.activations WHERE partition_id=p_partition
        AND incarnation=p_incarnation AND event_id=p_event AND kind=p_kind
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_ACTIVATION_REQUIRED';
    END IF;
    UPDATE home_auth.head SET revision=p_revision+1,digest=p_digest
     WHERE partition_id=p_partition AND incarnation=p_incarnation
       AND revision=p_revision;
    IF ROW_COUNT()<>1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_STALE_HEAD';
    END IF;
    INSERT INTO home_auth.events VALUES
        (p_partition,p_incarnation,p_event,p_request_sha,p_revision+1,p_digest,p_kind);
END//

CREATE PROCEDURE home_auth.reset_person_incarnation(
    IN p_partition VARCHAR(64), IN p_incarnation VARCHAR(64)
) SQL SECURITY DEFINER
BEGIN
    IF CHAR_LENGTH(p_incarnation)<>64 OR
       IS_USED_LOCK(CONCAT('kap2_person_', LEFT(SHA2(p_partition, 256), 40)))
       IS NULL OR IS_USED_LOCK(CONCAT('kap2_person_', LEFT(SHA2(p_partition, 256), 40)))
       <> CONNECTION_ID() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_RECOVERY_LANE_REQUIRED';
    END IF;
    UPDATE home_auth.head SET incarnation=p_incarnation,revision=0,digest='DENY_ALL'
     WHERE partition_id=p_partition AND incarnation<>p_incarnation;
    IF ROW_COUNT()<>1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_RECOVERY_FAILED';
    END IF;
END//

DELIMITER ;
