from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_k8s_policy_copy_matches():
    assert (ROOT / "policy/tools.rego").read_text() == (ROOT / "deploy/k8s/base/policy/tools.rego").read_text()
