"""harness/repo_intel.py — Layer 2: Repository Intelligence Engine & Semantic File Ranker.

Reference: PRD.md §4.2 | architecture.md §7.2
Builds token-cheap, semantically rich repo indices (file_tree, module_symbols,
dependency_graph, test_map) and performs 3-factor semantic re-ranking without
dumping raw file bodies into the context window.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from harness.contracts import RankedFile, RankedFileSet, RepoIndex
from harness.tools.navigation import BINARY_EXTENSIONS, JUNK_DIRS


class RepoIndexBuilder:
    """Builds and caches directory trees, symbol catalogs, and dependency graphs."""

    def __init__(
        self,
        repo_path: str = ".",
        output_dir: str | None = None,
        max_depth: int = 4,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.output_dir = Path(output_dir) if output_dir else self.repo_path / ".harness" / "repo_index"
        self.max_depth = max_depth

    def _compute_cache_signature(self) -> str:
        """Compute MD5 hash over repo status / key file modification times."""
        hash_md5 = hashlib.md5()
        file_count = 0
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in JUNK_DIRS and not d.startswith(".")]
            depth = len(Path(root).relative_to(self.repo_path).parts)
            if depth >= self.max_depth:
                dirs.clear()
                continue

            for f in sorted(files):
                if f.startswith(".") or any(f.endswith(ext) for ext in BINARY_EXTENSIONS):
                    continue
                p = Path(root) / f
                try:
                    stat = p.stat()
                    hash_md5.update(f"{p.name}:{stat.st_mtime}:{stat.st_size}".encode("utf-8"))
                    file_count += 1
                except OSError:
                    continue

        hash_md5.update(f"total:{file_count}".encode("utf-8"))
        return hash_md5.hexdigest()

    def build_index(self, force: bool = False) -> RepoIndex:
        """Build or retrieve cached repository index."""
        start_time = time.perf_counter()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_tree_path = self.output_dir / "file_tree.txt"
        module_symbols_path = self.output_dir / "module_symbols.json"
        dependency_graph_path = self.output_dir / "dependency_graph.json"
        test_map_path = self.output_dir / "test_map.json"
        cache_sig_path = self.output_dir / ".cache_sig"

        current_sig = self._compute_cache_signature()

        # Check if cache is valid
        if (
            not force
            and cache_sig_path.exists()
            and file_tree_path.exists()
            and module_symbols_path.exists()
            and dependency_graph_path.exists()
            and test_map_path.exists()
        ):
            saved_sig = cache_sig_path.read_text(encoding="utf-8").strip()
            if saved_sig == current_sig:
                try:
                    symbols = json.loads(module_symbols_path.read_text(encoding="utf-8"))
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    return RepoIndex(
                        file_tree_path=str(file_tree_path),
                        module_symbols_path=str(module_symbols_path),
                        dependency_graph_path=str(dependency_graph_path),
                        test_map_path=str(test_map_path),
                        embedding_index_path="",
                        total_files=len(symbols),
                        build_time_ms=latency_ms,
                    )
                except Exception:
                    pass

        # ─── 1. Build File Tree (Depth <= max_depth, filtered) ─────────────
        tree_lines: list[str] = [f"{self.repo_path.name}/"]
        all_code_files: list[Path] = []

        def _walk_tree(dir_path: Path, prefix: str = "", depth: int = 1) -> None:
            if depth > self.max_depth:
                return

            try:
                entries = sorted(list(dir_path.iterdir()), key=lambda p: (not p.is_dir(), p.name))
            except OSError:
                return

            filtered_entries: list[Path] = []
            for e in entries:
                if e.name in JUNK_DIRS or e.name.startswith("."):
                    continue
                if e.is_file() and any(e.name.endswith(ext) for ext in BINARY_EXTENSIONS):
                    continue
                filtered_entries.append(e)

            for i, entry in enumerate(filtered_entries):
                is_last = i == len(filtered_entries) - 1
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if entry.is_dir():
                    tree_lines.append(f"{prefix}{connector}{entry.name}/")
                    _walk_tree(entry, prefix + sub_prefix, depth + 1)
                else:
                    rel_p = entry.relative_to(self.repo_path)
                    tree_lines.append(f"{prefix}{connector}{entry.name} ({rel_p})")
                    all_code_files.append(entry)

        _walk_tree(self.repo_path)
        file_tree_path.write_text("\n".join(tree_lines) + "\n", encoding="utf-8")

        # ─── 2. Build Module Symbols ────────────────────────────────────────
        module_symbols: dict[str, list[dict[str, Any]]] = {}
        for file_path in all_code_files:
            rel_str = str(file_path.relative_to(self.repo_path))
            symbols_list: list[dict[str, Any]] = []

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if file_path.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=str(file_path))
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef):
                            methods = [
                                m.name for m in node.body
                                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                            ]
                            symbols_list.append({
                                "name": node.name,
                                "kind": "class",
                                "line_start": node.lineno,
                                "line_end": getattr(node, "end_lineno", node.lineno),
                                "methods": methods,
                            })
                        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols_list.append({
                                "name": node.name,
                                "kind": "function",
                                "line_start": node.lineno,
                                "line_end": getattr(node, "end_lineno", node.lineno),
                            })
                except SyntaxError:
                    # Fallback regex for python files with syntax errors
                    pass
            elif file_path.suffix in (".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"):
                # Regex extractor for JS/TS/Go/Rust/Java
                for idx, line in enumerate(content.splitlines(), 1):
                    m = re.match(r"^(?:export\s+)?(class|function|interface|type|fn|func|pub\s+fn|pub\s+struct)\s+([A-Za-z0-9_]+)", line.strip())
                    if m:
                        symbols_list.append({
                            "name": m.group(2),
                            "kind": m.group(1),
                            "line_start": idx,
                            "line_end": idx,
                        })

            module_symbols[rel_str] = symbols_list

        module_symbols_path.write_text(json.dumps(module_symbols, indent=2), encoding="utf-8")

        # ─── 3. Build Dependency Graph ──────────────────────────────────────
        dependency_graph: dict[str, list[str]] = defaultdict(list)
        for file_path in all_code_files:
            rel_str = str(file_path.relative_to(self.repo_path))
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            imported_modules: set[str] = set()
            if file_path.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=str(file_path))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imported_modules.add(alias.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imported_modules.add(node.module)
                except Exception:
                    pass
            elif file_path.suffix in (".js", ".jsx", ".ts", ".tsx"):
                for m in re.finditer(r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", content):
                    imported_modules.add(m.group(1))

            dependency_graph[rel_str] = sorted(list(imported_modules))

        dependency_graph_path.write_text(json.dumps(dependency_graph, indent=2), encoding="utf-8")

        # ─── 4. Build Test Map ──────────────────────────────────────────────
        test_map: dict[str, list[str]] = defaultdict(list)
        for src_rel in module_symbols.keys():
            src_stem = Path(src_rel).stem
            # Direct naming matching
            for other_rel in module_symbols.keys():
                if "test" in other_rel.lower():
                    other_stem = Path(other_rel).stem
                    if other_stem in (f"test_{src_stem}", f"{src_stem}_test") or src_stem in other_stem:
                        if other_rel != src_rel and other_rel not in test_map[src_rel]:
                            test_map[src_rel].append(other_rel)

            # Dependency matching
            for test_file, imports in dependency_graph.items():
                if "test" in test_file.lower():
                    src_module = src_rel.replace("/", ".").replace(".py", "")
                    if any(src_stem in imp or src_module in imp for imp in imports):
                        if test_file != src_rel and test_file not in test_map[src_rel]:
                            test_map[src_rel].append(test_file)

        test_map_path.write_text(json.dumps(test_map, indent=2), encoding="utf-8")
        cache_sig_path.write_text(current_sig, encoding="utf-8")

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return RepoIndex(
            file_tree_path=str(file_tree_path),
            module_symbols_path=str(module_symbols_path),
            dependency_graph_path=str(dependency_graph_path),
            test_map_path=str(test_map_path),
            embedding_index_path="",
            total_files=len(module_symbols),
            build_time_ms=latency_ms,
        )


class SemanticRanker:
    """3-factor semantic re-ranking engine across module symbol catalogs."""

    def _tokenize(self, text: str) -> list[str]:
        """Normalize and tokenize text into identifier words."""
        # Split CamelCase and snake_case
        s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        words = re.findall(r"[A-Za-z0-9_]+", s1.lower())
        return [w for w in words if len(w) > 1]

    def _compute_text_similarity(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Compute length-normalized term match similarity between 0.0 and 1.0."""
        if not query_tokens or not doc_tokens:
            return 0.0

        q_set = set(query_tokens)
        matches = sum(1 for w in doc_tokens if w in q_set)
        if matches == 0:
            return 0.0

        # Term overlap with log document length penalty
        score = matches / (math.sqrt(len(query_tokens)) * math.log2(len(doc_tokens) + 2))
        return min(1.0, max(0.0, score))

    def rank_files(
        self,
        query: str,
        repo_index: RepoIndex,
        repo_path: str = ".",
        suspected_files: list[str] | None = None,
        top_n: int = 5,
    ) -> RankedFileSet:
        """Rank repository files using 3-factor weighting (PRD §4.2.3)."""
        suspected_paths = set(suspected_files or [])
        symbols_path = Path(repo_index.module_symbols_path)
        dep_graph_path = Path(repo_index.dependency_graph_path)

        if not symbols_path.exists():
            return RankedFileSet(files=[], total_indexed=0, index_tokens_cost=0)

        module_symbols: dict[str, list[dict[str, Any]]] = json.loads(
            symbols_path.read_text(encoding="utf-8")
        )
        dep_graph: dict[str, list[str]] = {}
        if dep_graph_path.exists():
            try:
                dep_graph = json.loads(dep_graph_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        query_tokens = self._tokenize(query)
        scored_files: list[tuple[float, RankedFile]] = []

        for rel_path, symbols in module_symbols.items():
            # Build summary tokens
            summary_parts: list[str] = []
            for s in symbols:
                name = s.get("name", "")
                kind = s.get("kind", "")
                methods = s.get("methods", [])
                if methods:
                    summary_parts.append(f"{kind} {name} ({', '.join(methods)})")
                else:
                    summary_parts.append(f"{kind} {name}")

            symbol_summary = "; ".join(summary_parts) if summary_parts else Path(rel_path).name
            doc_text = f"{rel_path} {symbol_summary}"
            doc_tokens = self._tokenize(doc_text)

            # 1. Text Similarity (weight 0.5)
            text_sim = self._compute_text_similarity(query_tokens, doc_tokens)

            # 2. Exact Path / Symbol Match (weight 0.3)
            match_score = 0.0
            for sp in suspected_paths:
                if sp == rel_path or Path(sp).name == Path(rel_path).name:
                    match_score = 1.0
                    break
                elif Path(sp).stem in rel_path:
                    match_score = max(match_score, 0.7)

            # 3. Dependency Proximity (weight 0.2)
            dep_score = 0.0
            if suspected_paths:
                file_stem = Path(rel_path).stem
                for sp in suspected_paths:
                    sp_stem = Path(sp).stem
                    # Direct import match
                    imports = dep_graph.get(rel_path, [])
                    if any(sp_stem in imp for imp in imports):
                        dep_score = max(dep_score, 1.0)
                    sp_imports = dep_graph.get(sp, [])
                    if any(file_stem in imp for imp in sp_imports):
                        dep_score = max(dep_score, 1.0)

            # Combined 3-Factor Relevance Score
            final_score = round(min(1.0, (0.5 * text_sim) + (0.3 * match_score) + (0.2 * dep_score)), 3)

            # Count file lines
            line_count = 0
            full_p = Path(repo_path) / rel_path
            if full_p.exists():
                try:
                    line_count = len(full_p.read_text(encoding="utf-8", errors="ignore").splitlines())
                except OSError:
                    line_count = 0

            lang = "python" if rel_path.endswith(".py") else "typescript" if rel_path.endswith((".ts", ".tsx")) else "text"
            ranked_file = RankedFile(
                path=rel_path,
                relevance_score=final_score,
                symbol_summary=symbol_summary[:300],
                line_count=line_count,
                language=lang,
            )
            scored_files.append((final_score, ranked_file))

        # Sort descending by relevance score
        scored_files.sort(key=lambda x: x[0], reverse=True)
        top_files = [f for _, f in scored_files[:top_n]]

        token_cost = sum(len(f.symbol_summary.split()) + 10 for f in top_files)
        return RankedFileSet(
            files=top_files,
            total_indexed=len(module_symbols),
            index_tokens_cost=token_cost,
        )
