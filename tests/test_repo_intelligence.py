"""Unit tests for harness/repo_intel.py (Phase 4).

Validates RepoIndexBuilder (file_tree, module_symbols, dependency_graph, test_map),
cache invalidation, and SemanticRanker 3-factor file selection per PRD §4.2.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.repo_intel import RepoIndexBuilder, SemanticRanker


def create_sample_repo(repo_dir: Path) -> None:
    # Source modules
    src_dir = repo_dir / "src" / "auth"
    src_dir.mkdir(parents=True)

    service_py = src_dir / "service.py"
    service_py.write_text(
        "from src.auth.token import verify_token\n\n"
        "class AuthService:\n"
        "    def authenticate(self, user, token):\n"
        "        return verify_token(token)\n"
    )

    token_py = src_dir / "token.py"
    token_py.write_text(
        "def verify_token(token):\n"
        "    if not token:\n"
        "        raise ValueError('Invalid token')\n"
        "    return True\n"
    )

    db_dir = repo_dir / "src" / "db"
    db_dir.mkdir(parents=True)
    db_py = db_dir / "models.py"
    db_py.write_text(
        "class User:\n"
        "    def __init__(self, username):\n"
        "        self.username = username\n"
    )

    # Tests
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True)
    test_auth_py = tests_dir / "test_auth.py"
    test_auth_py.write_text(
        "from src.auth.service import AuthService\n\n"
        "def test_authenticate():\n"
        "    auth = AuthService()\n"
        "    assert auth.authenticate('admin', 'valid')\n"
    )

    # Junk dir that should be ignored
    junk = repo_dir / ".venv" / "lib"
    junk.mkdir(parents=True)
    (junk / "junk.py").write_text("# ignored\n")


def test_repo_index_builder_file_tree(tmp_path):
    create_sample_repo(tmp_path)

    builder = RepoIndexBuilder(repo_path=str(tmp_path))
    index = builder.build_index()

    tree_content = Path(index.file_tree_path).read_text()
    assert "src/auth/service.py" in tree_content or "service.py" in tree_content
    assert "src/auth/token.py" in tree_content or "token.py" in tree_content
    assert ".venv" not in tree_content
    assert "junk.py" not in tree_content


def test_module_symbols_generation(tmp_path):
    create_sample_repo(tmp_path)

    builder = RepoIndexBuilder(repo_path=str(tmp_path))
    index = builder.build_index()

    symbols_data = json.loads(Path(index.module_symbols_path).read_text())
    assert any("service.py" in k for k in symbols_data.keys())

    # Find service.py symbols
    service_key = next(k for k in symbols_data.keys() if "service.py" in k)
    symbols = symbols_data[service_key]
    assert any(s["name"] == "AuthService" and s["kind"] == "class" for s in symbols)


def test_dependency_graph_and_test_map(tmp_path):
    create_sample_repo(tmp_path)

    builder = RepoIndexBuilder(repo_path=str(tmp_path))
    index = builder.build_index()

    dep_graph = json.loads(Path(index.dependency_graph_path).read_text())
    assert any("service.py" in k for k in dep_graph.keys())

    test_map = json.loads(Path(index.test_map_path).read_text())
    # test_auth.py should map to service.py
    assert any("service.py" in k for k in test_map.keys())


def test_semantic_file_ranker_3_factor(tmp_path):
    create_sample_repo(tmp_path)

    builder = RepoIndexBuilder(repo_path=str(tmp_path))
    index = builder.build_index()

    ranker = SemanticRanker()
    ranked_set = ranker.rank_files(
        query="authenticate token NoneType crash in AuthService",
        repo_index=index,
        repo_path=str(tmp_path),
        suspected_files=["src/auth/service.py"],
        top_n=3,
    )

    assert len(ranked_set.files) >= 1
    top_file = ranked_set.files[0]
    assert "service.py" in top_file.path
    assert top_file.relevance_score > 0.5
    assert "AuthService" in top_file.symbol_summary


def test_index_cache_invalidation(tmp_path):
    create_sample_repo(tmp_path)

    builder = RepoIndexBuilder(repo_path=str(tmp_path))
    index1 = builder.build_index()

    # Re-running without changes should use cache
    index2 = builder.build_index()
    assert index1.build_time_ms is not None
    assert index2.file_tree_path == index1.file_tree_path

    # Modifying a file should invalidate cache
    token_py = tmp_path / "src" / "auth" / "token.py"
    token_py.write_text("# modified\ndef new_func(): pass\n")

    index3 = builder.build_index()
    symbols_data = json.loads(Path(index3.module_symbols_path).read_text())
    token_key = next(k for k in symbols_data.keys() if "token.py" in k)
    assert any(s["name"] == "new_func" for s in symbols_data[token_key])
