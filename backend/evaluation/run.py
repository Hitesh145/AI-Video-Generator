"""Command line: fetch the papers, store them once, check the question files, compare the search modes.

    python -m evaluation.run [--papers KEY ...] [--modes vector keyword hybrid]
                             [--validate-only] [--out PATH] [--user-email EMAIL]
"""

from __future__ import annotations

import argparse
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from evaluation.fetch_papers import fetch
from evaluation.ingest import ensure_paper
from evaluation.questions import load_question_set
from evaluation.runner import evaluate, render_markdown
from evaluation.validation import find_problems

EVALUATION_DIR = Path(__file__).resolve().parent
BACKEND_DIR = EVALUATION_DIR.parent
MANIFEST = EVALUATION_DIR / "papers.json"
QUESTIONS_DIR = EVALUATION_DIR / "data"
PAPERS_DIR = BACKEND_DIR / "data" / "eval_papers"
DEFAULT_OUT = EVALUATION_DIR / "results" / "latest.md"
DEFAULT_EMAIL = "evaluation@edugen.local"
ALL_MODES = ("vector", "keyword", "hybrid")


@dataclass
class Context:
    user_id: str
    storage: Any
    ingestor: Any
    searcher: Any
    ensure_document: Callable[[str, Path], str]      # (paper key, pdf path) -> stored document id
    paper_passages: Callable[[str], list[str]]       # document id -> the stored passages, one string each


def build_context(user_email: str) -> Context:
    """Wire the real services. The evaluation copies belong to a dedicated account that is created if missing."""
    from sqlalchemy import text

    from accounts.service import AccountService
    from papers.ingestor import PaperIngestor
    from rag.database import build_session_factory
    from rag.pg_repository import PostgresRAGRepository
    from rag.storage_service import RAGStorageService
    from retrieval.search import build_paper_searcher

    factory = build_session_factory()
    accounts = AccountService(factory)
    user = accounts.find_user(user_email) or accounts.signup(user_email, secrets.token_urlsafe(24))[0]
    repository = PostgresRAGRepository(factory)
    storage = RAGStorageService(repository)
    ingestor = PaperIngestor(storage)

    def paper_passages(document_id: str) -> list[str]:
        with factory() as session:
            rows = session.execute(
                text("SELECT text FROM rag_document_chunks WHERE document_id = :id ORDER BY sequence_index"),
                {"id": document_id},
            ).scalars()
            return list(rows)

    return Context(
        user_id=user.user_id,
        storage=storage,
        ingestor=ingestor,
        searcher=build_paper_searcher(storage, repository),
        ensure_document=lambda key, path: ensure_paper(path, user.user_id, storage, ingestor, PAPERS_DIR / key / "work"),
        paper_passages=paper_passages,
    )


def main(
    argv: list[str] | None = None,
    *,
    context_factory: Callable[[str], Context] | None = None,
    fetcher: Callable[[], dict[str, Path]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Compare the paper search modes on hand-checked questions.")
    parser.add_argument("--papers", nargs="*", default=None, help="paper keys to use (default: all available)")
    parser.add_argument("--modes", nargs="+", default=list(ALL_MODES), choices=ALL_MODES)
    parser.add_argument("--user-email", default=DEFAULT_EMAIL)
    parser.add_argument("--validate-only", action="store_true", help="only check the question files against the stored text")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--questions-dir", type=Path, default=QUESTIONS_DIR)
    args = parser.parse_args(argv)

    available = (fetcher or (lambda: fetch(MANIFEST, PAPERS_DIR)))()
    wanted = args.papers if args.papers else list(available)
    unknown = [key for key in wanted if key not in available]
    if unknown:
        print(f"Unknown or unavailable paper(s): {', '.join(unknown)}. Available: {', '.join(available) or 'none'}")
        return 2

    context = (context_factory or build_context)(args.user_email)
    results = []
    failed = False
    for key in wanted:
        document_id = context.ensure_document(key, available[key])
        print(f"{key}: stored as document {document_id}")
        question_file = Path(args.questions_dir) / f"{key}.json"
        if not question_file.exists():
            print(f"{key}: no question file yet ({question_file.name})")
            continue
        question_set = load_question_set(question_file)
        problems = find_problems(question_set, context.paper_passages(document_id))
        for problem in problems:
            print(f"{key}: {problem}")
        if problems:
            failed = True
            continue
        print(f"{key}: question file has no problems ({len(question_set.questions)} questions)")
        if not args.validate_only:
            results.append(evaluate(context.searcher, context.user_id, document_id, question_set, modes=args.modes))

    if failed:
        return 1
    if args.validate_only or not results:
        return 0

    report = render_markdown(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
