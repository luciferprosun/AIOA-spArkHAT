"""Explicit seeded synthetic canary, not provider performance certification.

Fault labels come from this fixture corpus, never from the verifiers themselves.
Paired miss statistics describe only complete injected-fault pairs. Callback
errors are reported separately, never laundered into successful detection.
"""
from datetime import datetime, timezone
from math import sqrt
from random import Random
from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.learning.contracts import CoreVerifierBinding, VerificationInput, VerificationVerdict


def run_canary(bindings,*,seed,cases=64):
    if (type(bindings) is not tuple or len(bindings)!=2
        or any(type(v) is not CoreVerifierBinding for v in bindings)
        or type(seed) is not int or not 0<=seed<2**32
        or type(cases) is not int or not 0<=cases<=256):
        raise ValueError('INVALID_SYNTHETIC_CANARY')
    rng=Random(seed);counts={'00':0,'01':0,'10':0,'11':0}
    incomplete=controls=false_positives=0;corpus=[]
    scope=OwnerScope('fixture-tenant','fixture-owner','fixture-space','fixture-slot')
    for index in range(cases):
        truth='Fixture fact '+str(index);kind=rng.randrange(4)
        claim=truth if kind==0 else truth+' but false' if kind==1 else 'Wrong fixture assertion '+str(index)
        fault=kind!=0;corpus.append((index,kind,canonical_sha256(claim)))
        request=VerificationInput(scope,'fixture-hat','fixture-task',claim,
            (('fixture-source','revision-1',canonical_sha256(truth),truth),),
            datetime(2030,1,1,tzinfo=timezone.utc))
        results=[]
        for binding in bindings:
            try:
                verdict=binding.verifier.verify(request)
                if type(verdict) is not VerificationVerdict or verdict.input_digest!=request.digest:
                    raise ValueError('INVALID_FIXTURE_VERDICT')
                results.append(verdict.supported)
            except Exception:
                results.append(None)
        if any(v is None for v in results):incomplete+=1;continue
        if fault:counts[''.join('1' if v else '0' for v in results)]+=1
        else:
            controls+=1
            false_positives+=sum(not v for v in results)
    n=sum(counts.values());p_a=(counts['10']+counts['11'])/n if n else None
    p_b=(counts['01']+counts['11'])/n if n else None
    joint=counts['11']/n if n else None;cov=joint-p_a*p_b if n else None
    variance=p_a*(1-p_a)*p_b*(1-p_b) if n else 0
    result={'mode':'SYNTHETIC_FIXTURE','authority':'NONE','provider_calls':0,'seed':seed,
        'cases':cases,'corpus_digest':canonical_sha256(corpus),'fault_pairs':n,
        'paired_counts':counts,'joint_misses':counts['11'],'joint_miss_rate':joint,
        'miss_rate_a':p_a,'miss_rate_b':p_b,'covariance':cov,
        'correlation':cov/sqrt(variance) if variance>0 else None,
        'complete_controls':controls,'false_positive_votes':false_positives,'incomplete_cases':incomplete,
        'statistics_status':'MEASURED_SYNTHETIC' if n else 'UNKNOWN_NO_COMPLETE_FAULT_PAIRS',
        'shared_instance':bindings[0].verifier is bindings[1].verifier,
        'shared_method':bindings[0].verifier_method==bindings[1].verifier_method,
        'shared_family':bindings[0].source_family==bindings[1].source_family,
        'independence_proven':False,'generalization':'UNVERIFIED'}
    return result
