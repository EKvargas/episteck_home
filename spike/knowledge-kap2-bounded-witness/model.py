"""Synthetic bounded Home witness model. No cloud, Frappe or real signing calls."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace


KEY = b"synthetic-checkpoint-key-not-for-production"
MAX_SUFFIX = 2  # Force rollover in the local failure model; not a production choice.


def digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def mac(*parts: object) -> str:
    return hmac.new(KEY, json.dumps(parts, separators=(",", ":")).encode(), "sha256").hexdigest()


class Denied(Exception):
    """An authorization or publication must fail closed."""


class CASConflict(Denied):
    """A delayed conditional head replacement lost its generation race."""


@dataclass(frozen=True)
class Checkpoint:
    sequence: int
    epoch: int
    authority_digest: str
    outcome_hash: str
    signature: str

    @classmethod
    def sign(cls, sequence: int, epoch: int, authority_digest: str,
             outcome_hash: str) -> Checkpoint:
        return cls(sequence, epoch, authority_digest, outcome_hash,
                   mac("checkpoint", sequence, epoch, authority_digest, outcome_hash))

    def valid(self) -> bool:
        return hmac.compare_digest(
            self.signature, mac("checkpoint", self.sequence, self.epoch,
                                self.authority_digest, self.outcome_hash)
        )


@dataclass(frozen=True)
class Event:
    sequence: int
    epoch: int
    allowed: bool
    authority_digest: str
    previous_hash: str
    outcome_hash: str

    @classmethod
    def commit(cls, sequence: int, epoch: int, allowed: bool,
               authority_digest: str, previous_hash: str) -> Event:
        return cls(sequence, epoch, allowed, authority_digest, previous_hash,
                   digest("COMMIT", sequence, epoch, allowed, authority_digest,
                          previous_hash))

    def valid(self) -> bool:
        return self.outcome_hash == digest(
            "COMMIT", self.sequence, self.epoch, self.allowed,
            self.authority_digest, self.previous_hash
        )


@dataclass(frozen=True)
class Head:
    generation: int
    state: str
    sequence: int
    epoch: int
    writer_identity: str
    authority_digest: str
    outcome_hash: str
    checkpoint_sequence: int
    event_id: str | None = None


class Witness:
    def __init__(self) -> None:
        initial = digest("authority", 0, 1, True)
        self.head = Head(1, "COMMITTED", 0, 1, "writer-1", initial,
                         "GENESIS", 0)
        self.checkpoints = {0: Checkpoint.sign(0, 1, initial, "GENESIS")}
        self.events: dict[int, Event] = {}
        self.slots: set[int] = set()  # Immutable reservations, including PENDING work.
        self.outage = False
        self.requests = {"head_get": 0, "checkpoint_get": 0,
                         "event_get": 0, "successor_get": 0, "head_cas": 0}

    def fresh_head(self) -> Head:
        self.requests["head_get"] += 1
        if self.outage:
            raise Denied("witness unavailable")
        return self.head

    def checkpoint(self, sequence: int) -> Checkpoint:
        self.requests["checkpoint_get"] += 1
        if self.outage or sequence not in self.checkpoints:
            raise Denied("checkpoint unavailable")
        return self.checkpoints[sequence]

    def event(self, sequence: int) -> Event:
        self.requests["event_get"] += 1
        if self.outage or sequence not in self.events:
            raise Denied("journal suffix unavailable")
        return self.events[sequence]

    def successor_exists(self, sequence: int) -> bool:
        self.requests["successor_get"] += 1
        if self.outage:
            raise Denied("immutable successor probe unavailable")
        return sequence in self.slots

    def cas(self, expected_generation: int, next_head: Head,
            *, lose_ack: bool = False) -> Head:
        self.requests["head_cas"] += 1
        if self.outage:
            raise Denied("witness unavailable")
        if self.head.generation != expected_generation:
            raise CASConflict("stale head generation")
        self.head = replace(next_head, generation=expected_generation + 1)
        if lose_ack:
            raise TimeoutError("synthetic lost publication response")
        return self.head


class Home:
    def __init__(self, witness: Witness) -> None:
        self.sequence = 0
        self.epoch = 1
        self.allowed = True
        self.authority_digest = witness.head.authority_digest
        self.restored_ready = True  # Intentionally untrusted.
        self.lane_owner: str | None = None

    def acquire(self, owner: str) -> None:
        if self.lane_owner is not None:
            raise Denied("partition fence lock busy")
        self.lane_owner = owner

    def release(self, owner: str) -> None:
        if self.lane_owner != owner:
            raise RuntimeError("wrong lock owner")
        self.lane_owner = None

    def restore_old_allow(self) -> None:
        self.sequence, self.epoch, self.allowed = 0, 1, True
        self.authority_digest = digest("authority", 0, 1, True)
        self.restored_ready = True


class Publisher:
    """Only this trusted module can write the witness; clients can still sign."""

    def __init__(self, home: Home, witness: Witness) -> None:
        self.home, self.witness = home, witness
        self.pending: tuple[str, bool, int, str] | None = None

    def begin(self, identity: str, event_id: str, *, allowed: bool,
              lose_ack: bool = False) -> None:
        self.home.acquire("writer")
        try:
            head = self.witness.fresh_head()
            if head.state != "COMMITTED" or identity != head.writer_identity:
                raise Denied("inactive writer or pending head")
            if (self.home.sequence, self.home.epoch, self.home.authority_digest) != (
                head.sequence, head.epoch, head.authority_digest
            ):
                raise Denied("local authority differs from witness")
            if head.sequence - head.checkpoint_sequence >= MAX_SUFFIX:
                raise Denied("checkpoint required before further work")
            if self.witness.successor_exists(head.sequence + 1):
                raise Denied("next immutable slot already reserved")
            self.witness.slots.add(head.sequence + 1)
            proposed = replace(head, state="PENDING", event_id=event_id)
            self.pending = (event_id, allowed, head.generation + 1, identity)
            self.witness.cas(head.generation, proposed, lose_ack=lose_ack)
        except (Denied, TimeoutError):
            self.home.release("writer")
            raise

    def commit(self, *, next_epoch: bool = False, lose_ack: bool = False) -> None:
        if self.home.lane_owner != "writer" or self.pending is None:
            raise RuntimeError("no guarded pending mutation")
        event_id, allowed, pending_generation, identity = self.pending
        try:
            head = self.witness.fresh_head()
            if (head.state, head.event_id, head.generation, head.writer_identity) != (
                "PENDING", event_id, pending_generation, identity
            ):
                raise Denied("pending publication mismatch")
            new_sequence = head.sequence + 1
            new_epoch = head.epoch + int(next_epoch)
            new_digest = digest("authority", new_sequence, new_epoch, allowed)
            # The protected DB procedure applies authority and fence together.
            self.home.sequence, self.home.epoch = new_sequence, new_epoch
            self.home.allowed, self.home.authority_digest = allowed, new_digest
            event = Event.commit(new_sequence, new_epoch, allowed,
                                 new_digest, head.outcome_hash)
            self.witness.events[new_sequence] = event
            next_identity = f"writer-{new_epoch}" if next_epoch else identity
            self.witness.cas(head.generation, replace(
                head, state="COMMITTED", sequence=new_sequence, epoch=new_epoch,
                writer_identity=next_identity, authority_digest=new_digest,
                outcome_hash=event.outcome_hash, event_id=None
            ), lose_ack=lose_ack)
        finally:
            self.pending = None
            self.home.release("writer")

    def checkpoint(self) -> None:
        self.home.acquire("writer")
        try:
            head = self.witness.fresh_head()
            if head.state != "COMMITTED":
                raise Denied("cannot checkpoint pending head")
            self.witness.checkpoints[head.sequence] = Checkpoint.sign(
                head.sequence, head.epoch, head.authority_digest, head.outcome_hash
            )
            self.witness.cas(head.generation, replace(
                head, checkpoint_sequence=head.sequence
            ))
        finally:
            self.home.release("writer")

    def crash(self) -> None:
        """Release a dead writer's local lock; leave external PENDING intact."""
        self.pending = None
        if self.home.lane_owner == "writer":
            self.home.release("writer")


class Reader:
    def __init__(self, home: Home, witness: Witness) -> None:
        self.home, self.witness = home, witness

    def authorize(self) -> bool:
        self.home.acquire("reader")
        try:
            return self.evaluate_locked()
        except Denied:
            return False
        finally:
            self.home.release("reader")

    def evaluate_locked(self, *, substituted_checkpoint: Checkpoint | None = None) -> bool:
        if self.home.lane_owner != "reader":
            raise RuntimeError("reader must hold partition fence lock")
        head = self.witness.fresh_head()  # No cached or restored READY substitute.
        if head.state != "COMMITTED":
            raise Denied("newer PENDING work")
        checkpoint = substituted_checkpoint or self.witness.checkpoint(head.checkpoint_sequence)
        if (not checkpoint.valid() or checkpoint.sequence != head.checkpoint_sequence
                or head.sequence - checkpoint.sequence > MAX_SUFFIX):
            raise Denied("stale or invalid checkpoint")
        sequence, epoch = checkpoint.sequence, checkpoint.epoch
        authority_digest, outcome_hash = checkpoint.authority_digest, checkpoint.outcome_hash
        while sequence < head.sequence:
            event = self.witness.event(sequence + 1)
            if not event.valid() or event.previous_hash != outcome_hash:
                raise Denied("missing or corrupt journal suffix")
            sequence, epoch = event.sequence, event.epoch
            authority_digest, outcome_hash = event.authority_digest, event.outcome_hash
        if (sequence, epoch, authority_digest, outcome_hash) != (
            head.sequence, head.epoch, head.authority_digest, head.outcome_hash
        ):
            raise Denied("head and bounded suffix mismatch")
        if (self.home.sequence, self.home.epoch, self.home.authority_digest) != (
            head.sequence, head.epoch, head.authority_digest
        ):
            raise Denied("restored or uncommitted Home authority")
        if self.witness.successor_exists(head.sequence + 1):
            raise Denied("newer immutable slot than mutable head")
        return self.home.allowed


def new_system() -> tuple[Home, Witness, Publisher, Reader]:
    witness = Witness()
    home = Home(witness)
    return home, witness, Publisher(home, witness), Reader(home, witness)
