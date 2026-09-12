"""Dependency-free admission adapter for the optional legacy terminal UI."""
import json


def operator_request(runtime, prompt, *, plain_chat=False, run_budget='0'):
    if prompt.lstrip().startswith('/'):
        return runtime.run_text_request(prompt)['transcript']
    result = runtime.assistant_request(prompt, mode='plain' if plain_chat else 'cpl',
        plan_options=None if plain_chat else {'run_budget_usd':run_budget})
    if result['mode'] == 'cpl':
        return ('CPL PLAN — NOT A FINAL ANSWER\n'+json.dumps(result['cpl'], ensure_ascii=False, indent=2)
                +'\nInspect the plan, then /cpl start RUN_ID PLAN_HASH NONCE in this process. Ctrl+X cancels an active CPL run.')
    return 'PLAIN CHAT — NOT CPL REVIEWED\n'+result['transcript']
