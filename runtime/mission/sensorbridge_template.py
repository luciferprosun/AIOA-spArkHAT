"""Deterministic SensorBridge simulator; no hardware, network or credentials."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    sequence: int
    temperature_c: float
    humidity_pct: float


def sample(sequence):
    if type(sequence) is not int or not 0 <= sequence <= 1000:
        raise ValueError('sequence must be an integer from 0 to 1000')
    return Sample(sequence, round(20 + sequence % 11 * .25, 2),
                  round(40 + sequence % 7 * .5, 2))


def simulate(count=3):
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError('count must be an integer from 1 to 32')
    return [sample(index).__dict__ for index in range(count)]
