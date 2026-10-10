# KAP-2 Local PERSON Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace direct serving DML, close uncertain authorization returns, and prove physical restore closure for the disconnected PERSON vertical.

**Architecture:** Keep PR #68's Home lane, evaluated-state digest, and Task 1 witness unchanged. MariaDB definer procedures perform only named authority mutations and exact-event head updates; the serving principal receives SELECT and EXECUTE, while recovery uses a separate principal. Authorization returns allow only after the Home transaction and lane release complete successfully.

**Tech Stack:** Python 3.11+, PyMySQL, MariaDB 10.11, disposable Frappe 15 bench, pytest.

**Spec:** [Procedure acceptance matrix](../../../spike/knowledge-kap2-person-vertical/PROCEDURE_ACCEPTANCE.md).

## Global Constraints

- Based on PR #68 exact head `0c8c0006ec115b9084e1393df572b5a753771bcc`.
- No production credential, schema, migration, server installation, cloud run, merge, or deployment.
- Direct-human PERSON only; CIRCLE issuance remains denied.

## Review Focus

- Serving grants show no INSERT/UPDATE/DELETE on Home authority or site tables.
- Procedure calls cannot stage a mutation without the caller owning the protected partition lane.
- An allow cannot return after lock, connection, rollback, or release uncertainty.
- Physical restoration of both older permissive databases cannot reopen admission.

## Tasks

- [x] Add failing principal and procedure tests; install narrowly scoped definer procedures and separate recovery principal in both disposable harnesses.
- [x] Move serving mutations and event/revision changes to those procedures while preserving transaction and witness order; rerun PERSON and bypass cases.
- [x] Add failure-injection tests for loss during witness comparison and lane cleanup; make allow publication depend on successful finalization.
- [x] Copy both stopped disposable MariaDB datadirs at a permissive state, advance to revocation, restore the older datadirs, and prove closed first read and selected fresh reauthorization.
- [x] Rerun focused MariaDB and Frappe suites, record cleanup and limits, update Knowledge progress, commit, push, and open one draft PR based on PR #68.
