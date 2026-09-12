"""Admission limits and explicit cost authorization, not provider billing claims."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math

from providers.exact import ExactCallError

CONTRACT_VERSION = 'cpl-1plus3plus1-v1'
PROMPT_VERSION = 'desktop-5ec74f8-cpl-v1'
BASE_IMPLEMENTATION_COMMIT = '20a53ff8872e3aff4b872a021b5a46110549450a'
INPUT_BOUND_POLICY = 'utf8-bytes-plus-framing-v1'


def load_cost_policy(path):
    """Explicit local operator input, never fetched, inferred or model-authored."""
    import json
    from pathlib import Path
    from providers.exact import _unique_object

    selected = Path(path)
    if not selected.is_file() or selected.stat().st_size > 65536:
        raise ExactCallError('INVALID_LIVE_POLICY_FILE')
    try:
        value = json.loads(selected.read_text(), object_pairs_hook=_unique_object)
        if (not isinstance(value, dict) or set(value) != {'live_enabled', 'session_budget_usd', 'quotes'}
                or value['live_enabled'] is not True or not isinstance(value['quotes'], dict)):
            raise ValueError()
        if money(value['session_budget_usd']) <= 0:
            raise ExactCallError('ZERO_BUDGET')
        return CostPolicy(True, str(value['session_budget_usd']), json.dumps(value['quotes'], allow_nan=False))
    except (OSError, ValueError, TypeError, RecursionError):
        raise ExactCallError('INVALID_LIVE_POLICY_FILE') from None


def money(value) -> Decimal:
    try:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > 100:
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise ExactCallError('INVALID_BUDGET_OR_PRICE') from None


@dataclass(frozen=True)
class Limits:
    draft_tokens: int = 1024
    critic_tokens: int = 512
    revision_tokens: int = 1024
    input_tokens: int = 32768
    response_bytes: int = 65536
    request_timeout_seconds: float = 20.0
    run_deadline_seconds: float = 120.0

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ExactCallError('INVALID_LIMITS')
        limits = cls(**value)
        for name, maximum in [('draft_tokens', 1024), ('critic_tokens', 512),
                              ('revision_tokens', 1024), ('input_tokens', 32768),
                              ('response_bytes', 65536)]:
            item = getattr(limits, name)
            if type(item) is not int or not 1 <= item <= maximum:
                raise ExactCallError('INVALID_LIMITS')
        for name, maximum in [('request_timeout_seconds', 30), ('run_deadline_seconds', 180)]:
            item = getattr(limits, name)
            if isinstance(item, bool) or not isinstance(item, (float, int)) or not math.isfinite(item) or not 0 < item <= maximum:
                raise ExactCallError('INVALID_LIMITS')
        return limits

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CostPolicy:
    live_enabled: bool = False
    session_budget_usd: str = '0'
    quotes_json: str = '{}'

    def admission(self, scope: str, models: tuple[str, ...], limits: Limits,
                  run_budget: str, reserved: Decimal) -> dict:
        import json

        if scope == 'TEST':
            return {'scope': 'TEST', 'upper_bound_usd': '0', 'run_budget_usd': '0',
                    'session_budget_usd': '0', 'prices': None, 'actual_usage': None,
                    'billing': 'LOCAL_HTTP_FIXTURE_NO_MODEL_PROVIDER'}
        cap, session_cap = money(run_budget), money(self.session_budget_usd)
        if not self.live_enabled:
            raise ExactCallError('LIVE_DISABLED')
        if cap <= 0 or session_cap <= 0:
            raise ExactCallError('ZERO_BUDGET')
        try:
            quotes = json.loads(self.quotes_json)
        except (ValueError, TypeError):
            raise ExactCallError('MISSING_PRICE_QUOTE') from None
        estimate = Decimal(0)
        bound_quotes = {}
        for model, output in zip((models[0], *models[1:], models[0]),
                                 (limits.draft_tokens, *([limits.critic_tokens] * 3), limits.revision_tokens)):
            quote = quotes.get(model) if isinstance(quotes, dict) else None
            if not isinstance(quote, dict):
                raise ExactCallError('MISSING_PRICE_QUOTE')
            if quote.get('input_bound_policy') != INPUT_BOUND_POLICY or quote.get('currency') != 'USD':
                raise ExactCallError('UNVERIFIED_COST_BOUND')
            try:
                timestamp = datetime.fromisoformat(quote['quoted_utc'])
                age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                if timestamp.tzinfo is None or not 0 <= age <= 86400:
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise ExactCallError('STALE_PRICE_QUOTE') from None
            input_price = money(quote.get('input_usd_per_million'))
            output_price = money(quote.get('output_usd_per_million'))
            estimate += (limits.input_tokens * input_price + output * output_price) / Decimal(1_000_000)
            bound_quotes[model] = {k: quote[k] for k in ('currency', 'input_usd_per_million',
                'output_usd_per_million', 'quoted_utc', 'input_bound_policy')}
        if estimate > cap or reserved + estimate > session_cap:
            raise ExactCallError('BUDGET_EXCEEDED')
        return {'scope': 'LIVE', 'upper_bound_usd': str(estimate), 'run_budget_usd': str(cap),
                'session_budget_usd': str(session_cap), 'prices': bound_quotes,
                'actual_usage': None, 'billing': 'CONSERVATIVE_ADMISSION_NOT_BILLING_GUARANTEE',
                'input_bound_policy': INPUT_BOUND_POLICY}
