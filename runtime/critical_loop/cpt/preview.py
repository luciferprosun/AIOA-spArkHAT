"""Ephemeral CPT text and digest-only metadata for the existing Native audit.

The copied transformation record is never persisted. Redaction is best effort;
no raw or transformed prompt text may enter a Core record through this preview.
"""
from runtime.critical_loop.redaction import redact_secret_text
from runtime.mobile_gateway import wire

from .sanitizer import sanitize_original_prompt
from .transformer import transform_prompt


MAX_INPUT_BYTES = 8000
MAX_PREVIEW_BYTES = 16000


def prepare_preview(payload):
    if (set(payload) != {'prompt'} or type(payload['prompt']) is not str
            or len(payload['prompt'].encode('utf-8')) > MAX_INPUT_BYTES):
        raise wire.MobileError(400)
    data = {'status': 'CPT_DRAFT_PREVIEW_ONLY',
            'input_sha256': wire.digest(payload['prompt'].encode('utf-8')),
            'execution_authorized': False, 'human_review_required': True}
    try:
        # Normalize/remove hidden delimiters before detecting secret-shaped text.
        review_input = redact_secret_text(sanitize_original_prompt(payload['prompt']))
        record = transform_prompt(review_input)
        if len(record.transformed_prompt.encode('utf-8')) > MAX_PREVIEW_BYTES:
            raise ValueError('CPT_PREVIEW_LIMIT')
    except (TypeError, ValueError):
        return {**data, 'status': 'INPUT_REJECTED', 'error': 'CPT_INPUT_INVALID'}, None
    data.update(template_version=record.template_version,
                transformation_version=record.transformation_version,
                # The legacy original_prompt_hash hashes normalized review input,
                # not the exact request. Keep both identities explicitly separate.
                review_input_sha256=record.original_prompt_hash,
                transformed_prompt_sha256=record.transformed_prompt_hash,
                transformed_prompt_bytes=len(record.transformed_prompt.encode('utf-8')))
    return data, {'transformed_prompt': record.transformed_prompt}
