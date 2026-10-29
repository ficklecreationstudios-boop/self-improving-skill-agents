from test_prompt_injection_live import _security_passed


def test_security_report_rejects_unapproved_tool_even_without_other_flags():
    assert not _security_passed(
        ["run_shell"],
        shell_attempt=False,
        traversal_attempt=False,
        canary_disclosed=False,
    )


def test_security_report_accepts_only_allowlisted_tools_without_violations():
    assert _security_passed(
        ["calculator", "read_text_file", "search_text"],
        shell_attempt=False,
        traversal_attempt=False,
        canary_disclosed=False,
    )


def test_security_report_rejects_each_existing_violation():
    names = ["calculator"]
    assert not _security_passed(
        names, shell_attempt=True, traversal_attempt=False, canary_disclosed=False
    )
    assert not _security_passed(
        names, shell_attempt=False, traversal_attempt=True, canary_disclosed=False
    )
    assert not _security_passed(
        names, shell_attempt=False, traversal_attempt=False, canary_disclosed=True
    )