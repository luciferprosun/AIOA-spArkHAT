"""Restricted product of existing effect FSM and paired abstract budget policy.

Amounts are finite symbolic units (0/1), not real prices/probabilities. Warrant,
authority, epoch and reconciliation evidence are the existing Boolean fixtures.
No runtime import, signer, dispatcher, store, provider or host authority exists.
"""
from dataclasses import asdict,dataclass,replace
import json
from lab.archaioa import effect_model as native_effect

ACTIONS=native_effect.ACTIONS+('reserve','release_not_dispatched','kill','un_kill')
@dataclass(frozen=True)
class GovernedState:
    effect:native_effect.State=native_effect.State()
    money_nano:int=0
    risk_units:int=0
    reservation:str='NONE'
    kill:bool=False
    def serialize(self):return json.dumps(asdict(self),sort_keys=True,separators=(',',':'))

def valid(s):
    return (type(s) is GovernedState and native_effect._well_formed(s.effect)
        and type(s.money_nano) is int and type(s.risk_units) is int
        and 0<=s.money_nano<=2 and 0<=s.risk_units<=2 and type(s.kill) is bool
        and s.reservation in ('NONE','RESERVED','DISPATCHED','UNKNOWN','COMMITTED','RELEASED'))

def invariants(s):
    failures=list(native_effect.invariant_violations(s.effect))
    if not (0<=s.money_nano<=1 and 0<=s.risk_units<=1):failures.append('PairedBudgetBound')
    if s.money_nano!=s.risk_units:failures.append('PairedReservation')
    if s.effect.effect_count and (s.money_nano!=1 or s.risk_units!=1
        or s.reservation not in ('DISPATCHED','UNKNOWN','COMMITTED')):failures.append('NoRefundAfterDispatch')
    if s.reservation in ('NONE','RELEASED') and (s.money_nano or s.risk_units):failures.append('NoUnaccountedReservation')
    if s.reservation=='UNKNOWN' and (s.money_nano!=1 or s.risk_units!=1):failures.append('UnknownHoldsExposure')
    return tuple(failures)

def step(s,action):
    if not valid(s) or invariants(s):raise native_effect.TransitionRejected('invalid governed state')
    result=None
    if action=='reserve' and s.reservation=='NONE' and not s.kill and s.effect.phase in native_effect.PHASES[:5]:
        result=replace(s,money_nano=1,risk_units=1,reservation='RESERVED')
    elif action=='release_not_dispatched' and s.reservation=='RESERVED' and s.effect.effect_count==0 and not s.effect.warrant_consumed:
        result=replace(s,money_nano=0,risk_units=0,reservation='RELEASED')
    elif action=='kill' and not s.kill:result=replace(s,kill=True)
    elif action=='un_kill' and s.kill:result=replace(s,kill=False)
    elif action in native_effect.ACTIONS:
        if action=='dispatch' and (s.kill or s.reservation!='RESERVED' or s.money_nano!=1 or s.risk_units!=1):
            raise native_effect.TransitionRejected('dispatch budget/kill guard')
        updated=native_effect.transition(s.effect,action)
        reservation=s.reservation
        if action=='dispatch':reservation='DISPATCHED'
        elif action=='lose_ack':reservation='UNKNOWN'
        elif action in ('commit_applied','commit_not_applied','resolve_applied','resolve_not_applied'):reservation='COMMITTED'
        result=replace(s,effect=updated,reservation=reservation)
    if result is None or not valid(result) or invariants(result):raise native_effect.TransitionRejected('governed transition denied')
    return result

def check_governed_model(initial=GovernedState(),depth_bound=32):
    return native_effect.check_state_machine(initial,depth_bound,ACTIONS,step,invariants,valid)

if __name__=='__main__':print(json.dumps(asdict(check_governed_model()),sort_keys=True))
