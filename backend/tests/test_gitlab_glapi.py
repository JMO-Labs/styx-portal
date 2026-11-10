"""Shared stdlib GitLab/GitHub API client glapi.py (issue #16)."""

import sys

import pytest

from tests.gitlab_stub import DEPLOY, load, stdlib_only

GLAPI = DEPLOY / "gitlab-common/glapi.py"


@pytest.fixture
def glapi():
    return load(GLAPI, "glapi_t")


def test_redact_replaces_all_tokens(glapi):
    assert glapi.redact("a TOK1 b TOK2 TOK1", ["TOK1", "TOK2", "", None]) == "a *** b *** ***"


def test_client_non_json_is_api_error(glapi, serve):
    stub = serve(lambda *a: (200, b"<html>login</html>"))
    with pytest.raises(glapi.ApiError, match="not JSON"):
        glapi.Client(stub.base, {}).call("GET", "/x")


def test_client_http_error_carries_code(glapi, serve):
    stub = serve(lambda *a: (403, b"secret body text"))
    with pytest.raises(glapi.ApiError) as e:
        glapi.Client(stub.base, {}).call("GET", "/x")
    assert e.value.code == 403 and "secret body" not in str(e.value)


def test_project_path_encodes(glapi):
    assert glapi.project_path("grp/sub/proj") == "/projects/grp%2Fsub%2Fproj"
    assert glapi.project_path("42") == "/projects/42"


def test_ssl_context_bad_ca_is_api_error(glapi, tmp_path):
    assert glapi.ssl_context(None) is None
    with pytest.raises(glapi.ApiError, match="GITLAB_CA_FILE"):
        glapi.ssl_context(str(tmp_path / "missing.pem"))


def test_mirror_still_imports_shared_client():
    mod = load(DEPLOY / "gitlab-mirror/mirror_bootstrap.py", "mirror_bootstrap_t")
    assert mod.Client is sys.modules["glapi"].Client
    assert mod.ApiError is sys.modules["glapi"].ApiError


def test_glapi_stdlib_only():
    assert stdlib_only(GLAPI) == set()
