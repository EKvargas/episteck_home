"""Synthetic publisher-process schedules; GCS and MariaDB semantics are modeled."""

from __future__ import annotations

from dataclasses import dataclass, replace


class Denied(Exception):
    pass


class Conflict(Denied):
    pass


@dataclass(frozen=True)
class Head:
    generation: int
    sequence: int
    state: str
    publisher_epoch: int
    publisher_identity: str
    allowed: bool
    event_id: str | None = None


@dataclass(frozen=True)
class HeadWrite:
    expected_generation: int
    next_head: Head


class System:
    def __init__(self) -> None:
        self.head = Head(1, 0, "COMMITTED", 1, "publisher-1", True)
        self.db_sequence = 0
        self.db_publisher_epoch = 1
        self.db_publisher_identity = "publisher-1"
        self.db_allowed = True
        self.slots: set[int] = set()  # Immutable reservation history.
        self.outcomes: set[int] = set()
        self.lock_owner: str | None = None
        self.connection_nonce = 0

    def acquire(self, instance: str) -> int:
        if self.lock_owner is not None:
            raise Denied("partition lock busy")
        self.lock_owner = instance
        self.connection_nonce += 1
        return self.connection_nonce

    def release(self, instance: str, nonce: int) -> None:
        if self.lock_owner != instance or self.connection_nonce != nonce:
            raise Denied("connection fence lost")
        self.lock_owner = None

    def disconnect(self, instance: str) -> None:
        if self.lock_owner == instance:
            self.lock_owner = None
            self.connection_nonce += 1

    def cas(self, expected_generation: int, next_head: Head) -> Head:
        # Storage checks only the generation. The publisher must validate bytes.
        if self.head.generation != expected_generation:
            raise Conflict("stale external generation")
        self.head = replace(next_head, generation=expected_generation + 1)
        return self.head

    def deliver(self, request: HeadWrite) -> Head:
        return self.cas(request.expected_generation, request.next_head)

    def authorize(self) -> bool:
        head = self.head  # Synthetic fresh current-head read under a DB read lock.
        if head.state != "COMMITTED" or head.sequence + 1 in self.slots:
            return False
        if (self.db_sequence, self.db_publisher_epoch, self.db_publisher_identity,
                self.db_allowed) != (head.sequence, head.publisher_epoch,
                                    head.publisher_identity, head.allowed):
            return False
        return self.db_allowed

    def takeover(self, new_identity: str) -> None:
        nonce = self.acquire("operator")
        try:
            old = self.head
            if old.state != "COMMITTED":
                raise Denied("pending outcome requires reconciliation")
            if old.sequence + 1 in self.slots:
                raise Denied("unknown immutable successor")
            if (self.db_sequence, self.db_publisher_epoch, self.db_publisher_identity,
                    self.db_allowed) != (old.sequence, old.publisher_epoch,
                                        old.publisher_identity, old.allowed):
                raise Denied("DB and witness disagree")
            sequence = old.sequence + 1
            self.slots.add(sequence)  # Durable epoch event before head can advance.
            pending = self.cas(old.generation, replace(
                old, state="PENDING", event_id=f"takeover-{sequence}"
            ))
            self.db_sequence = sequence
            self.db_publisher_epoch = old.publisher_epoch + 1
            self.db_publisher_identity = new_identity
            self.outcomes.add(sequence)
            self.cas(pending.generation, replace(
                pending, sequence=sequence, state="COMMITTED",
                publisher_epoch=self.db_publisher_epoch,
                publisher_identity=new_identity, event_id=None
            ))
        finally:
            self.release("operator", nonce)


class PublisherProcess:
    def __init__(self, system: System, instance: str, identity: str) -> None:
        self.system, self.instance, self.identity = system, instance, identity
        self.nonce: int | None = None
        self.event_id: str | None = None
        self.allowed: bool | None = None

    def begin(self, event_id: str, *, allowed: bool) -> None:
        nonce = self.system.acquire(self.instance)
        try:
            head = self.system.head  # Fresh witness head, never a restart cache.
            if head.state != "COMMITTED":
                raise Denied("pending outcome requires reconciliation")
            if head.publisher_identity != self.identity:
                raise Denied("inactive publisher identity")
            if (self.system.db_sequence, self.system.db_publisher_epoch,
                    self.system.db_publisher_identity) != (
                head.sequence, head.publisher_epoch, head.publisher_identity
            ):
                raise Denied("DB and witness publisher fence disagree")
            sequence = head.sequence + 1
            if sequence in self.system.slots:
                raise Denied("immutable successor already reserved")
            self.system.slots.add(sequence)
            self.system.cas(head.generation, replace(
                head, state="PENDING", event_id=event_id
            ))
            self.nonce, self.event_id, self.allowed = nonce, event_id, allowed
        except Denied:
            self.system.release(self.instance, nonce)
            raise

    def _require_connection(self) -> None:
        if (self.nonce is None or self.system.lock_owner != self.instance
                or self.system.connection_nonce != self.nonce):
            raise Denied("connection fence lost")

    def commit_db(self) -> HeadWrite:
        self._require_connection()
        head = self.system.head
        if (head.state, head.event_id, head.publisher_identity) != (
            "PENDING", self.event_id, self.identity
        ):
            raise Denied("pending head changed")
        sequence = head.sequence + 1
        self.system.db_sequence = sequence
        self.system.db_allowed = bool(self.allowed)
        self.system.outcomes.add(sequence)
        return HeadWrite(head.generation, replace(
            head, sequence=sequence, state="COMMITTED", allowed=bool(self.allowed),
            event_id=None
        ))

    def commit(self) -> None:
        request = self.commit_db()
        self.system.deliver(request)
        assert self.nonce is not None
        self.system.release(self.instance, self.nonce)
        self.nonce = None

    def disconnect(self) -> None:
        self.system.disconnect(self.instance)
        self.nonce = None
