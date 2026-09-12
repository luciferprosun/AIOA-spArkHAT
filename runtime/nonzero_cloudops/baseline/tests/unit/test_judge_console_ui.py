from aioa_cloudops_agent.local_api.judge_ui import (
    JUDGE_UI_BODY,
    JUDGE_UI_SCRIPT,
    JUDGE_UI_STYLE,
    judge_ui_headers,
)


def test_console_has_one_primary_flow_and_truthful_runtime_labels() -> None:
    assert "Evidence first" in JUDGE_UI_BODY
    assert "Demo sandbox" in JUDGE_UI_BODY
    assert "Portable /" in JUDGE_UI_BODY
    assert "Strands" in JUDGE_UI_BODY
    assert "Nothing here is live AWS" in JUDGE_UI_BODY
    assert JUDGE_UI_BODY.count("data-scenario ") == 2
    assert all(
        stage in JUDGE_UI_BODY
        for stage in (
            'data-stage="observe"',
            'data-stage="evidence"',
            'data-stage="proposal"',
            'data-stage="policy"',
            'data-stage="approval"',
            'data-stage="execution"',
            'data-stage="verification"',
            'data-stage="receipt"',
        )
    )


def test_console_handles_refresh_slow_requests_stale_tabs_and_duplicate_clicks() -> None:
    assert "if (ui.busy) return;" in JUDGE_UI_SCRIPT
    assert "button.disabled = !ui.connected || ui.busy" in JUDGE_UI_SCRIPT
    assert "[403, 409].includes(error.status)" in JUDGE_UI_SCRIPT
    assert "A stale or conflicting action was rejected" in JUDGE_UI_SCRIPT
    assert "result.reconciled === true" in JUDGE_UI_SCRIPT
    assert "No duplicate mutation" in JUDGE_UI_SCRIPT
    assert "fragment.get('run')" in JUDGE_UI_SCRIPT
    assert "history.replaceState" in JUDGE_UI_SCRIPT
    assert "credentials: 'same-origin'" in JUDGE_UI_SCRIPT


def test_console_is_responsive_accessible_and_uses_no_external_assets() -> None:
    assert "@media (max-width: 700px)" in JUDGE_UI_STYLE
    assert "prefers-reduced-motion" in JUDGE_UI_STYLE
    assert "focus-visible" in JUDGE_UI_STYLE
    assert 'aria-live="polite"' in JUDGE_UI_BODY
    assert 'class="skip-link"' in JUDGE_UI_BODY
    assert "localStorage" not in JUDGE_UI_BODY
    assert "sessionStorage" not in JUDGE_UI_BODY
    assert "http://" not in JUDGE_UI_BODY
    assert "https://" not in JUDGE_UI_BODY

    headers = judge_ui_headers({"cache-control": "no-store"})
    policy = headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy
    assert "style-src 'sha256-" in policy
    assert "script-src 'sha256-" in policy
    assert "unsafe-inline" not in policy
