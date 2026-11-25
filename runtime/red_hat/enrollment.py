"""Public enrollment supplied by the trusted launcher."""

from dataclasses import dataclass

from runtime.red_hat.witness import RegisteredExecutor


@dataclass(frozen=True, slots=True)
class ExecutorEnrollment:
    executor: RegisteredExecutor
    key_epoch: int
    valid_from: int
    valid_until: int
    revoked: bool = False

    def __post_init__(self):
        if (type(self.executor) is not RegisteredExecutor
                or type(self.revoked) is not bool
                or not all(type(value) is int for value in (
                    self.key_epoch, self.valid_from, self.valid_until))
                or not 0 < self.key_epoch < 2**63
                or not 0 < self.valid_from < self.valid_until < 2**63):
            raise ValueError("BROKER_ENROLLMENT")

    def permits(self, request, now):
        return (
            type(now) is int
            and not self.revoked
            and self.valid_from <= now < self.valid_until
            and request.executor_id == self.executor.executor
            and request.executor_key_id == self.executor.key_id
            and request.key_epoch == self.key_epoch
        )
