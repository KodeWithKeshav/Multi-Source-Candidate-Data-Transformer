"""CLI — the only user interface for the transformer pipeline.

Orchestrates the full pipeline:
    Ingest → Adapt → Normalize → Resolve Identity → Merge → Assemble → Project → Validate → Write

Optionally generates:
    Decision Log (JSON) + Quality Dashboard (JSON) + HTML Report

Uses ``click`` for argument parsing. All source flags are optional,
but at least one structured (CSV or ATS) and one unstructured (GitHub
or notes) source must be supplied.
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from pathlib import Path

import click

from transformer.adapters.ats_adapter import AtsAdapter
from transformer.adapters.csv_adapter import CsvAdapter
from transformer.adapters.github_adapter import (
    GitHubAdapter,
    fetch_github_profile,
    fetch_github_repos,
)
from transformer.adapters.notes_adapter import NotesAdapter
from transformer.assemble import assemble_profile
from transformer.identity import resolve_identities
from transformer.ingest import (
    ingest_file,
    ingest_github_usernames,
    make_github_source_document,
)
from transformer.merge import merge_observations
from transformer.models import FieldObservation, SourceType
from transformer.normalize import normalize_observations
from transformer.project import (
    get_default_projection_config,
    load_projection_config,
    project,
)
from transformer.validate import ValidationError, validate_output

logger = logging.getLogger("transformer")


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI run."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ------------------------------------------------------------------
# Pipeline result container
# ------------------------------------------------------------------

class PipelineResult:
    """Container for all pipeline outputs — both final and intermediate."""

    __slots__ = (
        "projected", "candidate_profiles", "warnings",
        "total_observations", "sources_used",
    )

    def __init__(
        self,
        projected: list[dict],
        candidate_profiles: list,
        warnings: list[str],
        total_observations: int,
        sources_used: set[str],
    ):
        self.projected = projected
        self.candidate_profiles = candidate_profiles
        self.warnings = warnings
        self.total_observations = total_observations
        self.sources_used = sources_used


# ------------------------------------------------------------------
# Pipeline orchestrator
# ------------------------------------------------------------------

def run_pipeline(
    csv_paths: list[str],
    ats_paths: list[str],
    github_user_files: list[str],
    notes_paths: list[str],
    config_path: str | None,
    tier_weights: dict[str, float] | None = None,
) -> PipelineResult:
    """Execute the full transformation pipeline.

    Returns a ``PipelineResult`` containing projected outputs and
    intermediate data needed for report generation.
    """
    warnings: list[str] = []

    # ---- 1. Load projection config ----
    if config_path:
        proj_config = load_projection_config(config_path)
    else:
        proj_config = get_default_projection_config()

    # ---- 2. Ingest & Adapt ----
    all_observations: list[FieldObservation] = []

    # CSV sources
    csv_adapter = CsvAdapter()
    for path in csv_paths:
        try:
            doc = ingest_file(path, forced_type=SourceType.CSV)
            obs = csv_adapter.adapt(doc)
            all_observations.extend(obs)
            logger.info("CSV %s: %d observations", path, len(obs))
        except Exception as exc:
            msg = f"Failed to process CSV {path}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    # ATS JSON sources
    ats_adapter = AtsAdapter()
    for path in ats_paths:
        try:
            doc = ingest_file(path, forced_type=SourceType.ATS)
            obs = ats_adapter.adapt(doc)
            all_observations.extend(obs)
            logger.info("ATS %s: %d observations", path, len(obs))
        except Exception as exc:
            msg = f"Failed to process ATS {path}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    # GitHub sources
    gh_adapter = GitHubAdapter()
    for user_file in github_user_files:
        try:
            usernames = ingest_github_usernames(user_file)
        except Exception as exc:
            msg = f"Failed to read GitHub usernames from {user_file}: {exc}"
            logger.warning(msg)
            warnings.append(msg)
            continue

        for username in usernames:
            try:
                profile = fetch_github_profile(username)
                repos = fetch_github_repos(username)
                if not profile:
                    msg = f"GitHub user '{username}': no profile data (may be private/nonexistent)"
                    logger.warning(msg)
                    warnings.append(msg)
                    continue
                doc = make_github_source_document(username, profile, repos)
                obs = gh_adapter.adapt(doc)
                all_observations.extend(obs)
                logger.info("GitHub %s: %d observations", username, len(obs))
            except Exception as exc:
                msg = f"GitHub API failed for '{username}': {exc}"
                logger.warning(msg)
                warnings.append(msg)

    # Notes sources
    notes_adapter = NotesAdapter()
    for path in notes_paths:
        try:
            doc = ingest_file(path, forced_type=SourceType.NOTES)
            obs = notes_adapter.adapt(doc)
            all_observations.extend(obs)
            logger.info("Notes %s: %d observations", path, len(obs))
        except Exception as exc:
            msg = f"Failed to process notes {path}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    if not all_observations:
        logger.error("No observations produced from any source.")
        return PipelineResult(
            projected=[], candidate_profiles=[], warnings=warnings,
            total_observations=0, sources_used=set(),
        )

    # ---- 3. Normalize ----
    all_observations = normalize_observations(all_observations)

    # ---- 4. Resolve Identity ----
    clusters = resolve_identities(all_observations)

    # ---- 5–6. Merge & Assemble per candidate ----
    projected_outputs: list[dict] = []
    candidate_profiles = []
    for cid, obs_group in sorted(clusters.items()):
        merged, provenance_log = merge_observations(obs_group, tier_weights)
        profile = assemble_profile(cid, merged, provenance_log)
        candidate_profiles.append(profile)

        # ---- 7. Project ----
        projected = project(profile, proj_config)

        # ---- 8. Validate ----
        try:
            validated = validate_output(projected, proj_config)
            projected_outputs.append(validated)
        except ValidationError as exc:
            msg = f"Validation failed for candidate {cid}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    # ---- Summary ----
    sources_used = set()
    for obs in all_observations:
        sources_used.add(obs.source.value)

    click.echo(f"\n{'='*60}", err=True)
    click.echo(f"  Run Summary", err=True)
    click.echo(f"{'='*60}", err=True)
    click.echo(f"  Candidates produced : {len(projected_outputs)}", err=True)
    click.echo(f"  Sources used        : {', '.join(sorted(sources_used))}", err=True)
    click.echo(f"  Total observations  : {len(all_observations)}", err=True)
    if warnings:
        click.echo(f"  Warnings            : {len(warnings)}", err=True)
        for w in warnings:
            click.echo(f"    ⚠  {w}", err=True)
    else:
        click.echo(f"  Warnings            : 0", err=True)
    click.echo(f"{'='*60}\n", err=True)

    return PipelineResult(
        projected=projected_outputs,
        candidate_profiles=candidate_profiles,
        warnings=warnings,
        total_observations=len(all_observations),
        sources_used=sources_used,
    )


# ------------------------------------------------------------------
# Click CLI
# ------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Multi-Source Candidate Data Transformer."""
    pass


@cli.command()
@click.option("--csv", "csv_paths", multiple=True, type=click.Path(exists=True),
              help="Path to a recruiter CSV file.")
@click.option("--ats", "ats_paths", multiple=True, type=click.Path(exists=True),
              help="Path to an ATS JSON export file.")
@click.option("--github-users", "github_user_files", multiple=True, type=click.Path(exists=True),
              help="Path to a text file containing GitHub usernames (one per line).")
@click.option("--notes", "notes_patterns", multiple=True,
              help="Path/glob pattern for recruiter notes (.txt files).")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to a projection config JSON file. Defaults to full schema.")
@click.option("--out", "out_path", type=click.Path(), required=True,
              help="Output path for the result JSON file.")
@click.option("--report", "generate_report", is_flag=True, default=False,
              help="Generate HTML report + decision log + quality dashboard.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Enable verbose (debug) logging.")
def run(
    csv_paths: tuple[str, ...],
    ats_paths: tuple[str, ...],
    github_user_files: tuple[str, ...],
    notes_patterns: tuple[str, ...],
    config_path: str | None,
    out_path: str,
    generate_report: bool,
    verbose: bool,
) -> None:
    """Run the transformation pipeline."""
    _setup_logging(verbose)

    # Expand notes glob patterns
    notes_paths: list[str] = []
    for pattern in notes_patterns:
        expanded = glob.glob(pattern)
        if expanded:
            notes_paths.extend(sorted(expanded))
        else:
            # Treat as a literal path
            notes_paths.append(pattern)

    # Validate: at least one structured + one unstructured
    has_structured = bool(csv_paths or ats_paths)
    has_unstructured = bool(github_user_files or notes_paths)

    if not has_structured or not has_unstructured:
        click.echo(
            "Error: At least one structured source (--csv or --ats) "
            "AND one unstructured source (--github-users or --notes) "
            "must be supplied.",
            err=True,
        )
        sys.exit(1)

    # Run pipeline
    result = run_pipeline(
        csv_paths=list(csv_paths),
        ats_paths=list(ats_paths),
        github_user_files=list(github_user_files),
        notes_paths=notes_paths,
        config_path=config_path,
    )

    # Write projected output — deterministic (sorted keys, consistent formatting)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    output_json = json.dumps(result.projected, indent=2, sort_keys=True, ensure_ascii=False)
    out.write_text(output_json + "\n", encoding="utf-8")
    click.echo(f"Output written to {out_path}", err=True)

    # ---- Optional: Generate report artifacts ----
    if generate_report and result.candidate_profiles:
        from transformer.dashboard import compile_dashboard
        from transformer.explain import compile_all_decision_logs
        from transformer.report import generate_report as gen_report

        out_dir = out.parent

        # Decision logs
        decision_logs = compile_all_decision_logs(result.candidate_profiles)
        decision_path = out_dir / "decision_log.json"
        decision_path.write_text(
            json.dumps(decision_logs, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        click.echo(f"Decision log written to {decision_path}", err=True)

        # Quality dashboard
        dashboard = compile_dashboard(
            profiles=result.candidate_profiles,
            total_observations=result.total_observations,
            sources_used=result.sources_used,
            warnings=result.warnings,
        )
        dashboard_path = out_dir / "quality_dashboard.json"
        dashboard_path.write_text(
            json.dumps(dashboard, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        click.echo(f"Quality dashboard written to {dashboard_path}", err=True)

        # HTML report
        report_path = out_dir / "report.html"
        gen_report(
            projected_candidates=result.projected,
            decision_logs=decision_logs,
            quality_dashboard=dashboard,
            warnings=result.warnings,
            output_path=str(report_path),
        )
        click.echo(f"HTML report written to {report_path}", err=True)
