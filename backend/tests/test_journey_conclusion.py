import pytest
from troubleshooter.analysis.journey import _actionable_conclusion

FAILURE = {
    "service": "cm-acct-scene",
    "api": "/api/account",
    "reasons": ["HTTP 500"],
}
NODE = {
    "service": "cm-acct-scene",
    "api": "/api/account",
    "peer_service": "core-banking",
}


@pytest.mark.parametrize(
    ("domain", "expected_title", "expected_owner"),
    [
        ("upstream", "上游到 CM 的请求出现问题", "上游系统"),
        ("cm", "CM 内部 cm-acct-scene 出现问题", "CM Support"),
        ("downstream", "CM 访问下游 API 时出现问题", "下游 Support"),
        ("unknown", "故障环节暂时无法确认", "联合排查"),
    ],
)
def test_actionable_conclusion_names_fault_domain_and_owner(
    domain: str,
    expected_title: str,
    expected_owner: str,
):
    conclusion = _actionable_conclusion(domain, NODE, FAILURE, "响应返回")

    assert conclusion["title"] == expected_title
    assert conclusion["owner"] == expected_owner
    assert conclusion["action"]
