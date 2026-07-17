"""CLI commands for the content engine: `gen-topics`, `gen-script`.

Mounted automatically by cli.py (it imports this module and calls `register`), so this
phase never edits the shared cli.py file.
"""

from __future__ import annotations

from typing import Optional

import typer

from ..db.engine import SessionLocal
from ..db.models import Topic
from ..logging_setup import get_logger, setup_logging
from . import script_generator, topic_backlog
from .research_gate import ResearchRejected

log = get_logger("content.commands")


def register(app: typer.Typer) -> None:
    @app.command("gen-topics")
    def gen_topics(
        n: int = typer.Option(5, "--n", help="How many new topics to suggest via LLM"),
        category: str = typer.Option("maritime", "--category", help="Sub-niche: maritime|aviation|industrial|rail|structural|fire"),
    ) -> None:
        """Seed the backlog from seed_topics.yaml, then ask the LLM for N more angles."""
        setup_logging()
        added = topic_backlog.seed_backlog()
        if added:
            typer.echo(f"Seeded {added} topic(s) from seed_topics.yaml.")
        created = topic_backlog.suggest_topics(n, category=category)
        if not created:
            typer.echo("No new topics accepted (all duplicates, or LLM returned none).")
            return
        for t in created:
            typer.echo(f"[{t.id}] {t.title} — {t.angle}")

    @app.command("gen-script")
    def gen_script(
        topic_id: Optional[int] = typer.Option(
            None, "--topic-id", help="Topic id to script; defaults to the oldest backlog topic"
        ),
    ) -> None:
        """Run research_gate + script_generator for one topic; writes output/<id>/script.json."""
        setup_logging()
        with SessionLocal() as s:
            topic = s.get(Topic, topic_id) if topic_id is not None else topic_backlog.pick_next()
        if topic is None:
            typer.echo("No topic found (backlog empty, or bad --topic-id).")
            raise typer.Exit(code=1)

        try:
            result = script_generator.generate(topic)
        except ResearchRejected as exc:
            typer.echo(f"Research gate rejected topic {topic.id} ({topic.title}): {exc}")
            raise typer.Exit(code=1) from exc

        typer.echo(
            f"Script written for topic {topic.id} ({topic.title}): "
            f"{len(result.narration.split())} words, {len(result.shot_list)} shots, "
            f"pattern={result.pattern}, research_depth={result.research_depth}"
        )
