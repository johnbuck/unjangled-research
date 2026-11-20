#!/usr/bin/env python3
"""
Deep Research Engine — run state scaffold (not a runtime orchestrator)

Given a research query and a depth mode, this script displays the phase
instruction templates for exactly the phases the skill's docs give that
mode, and it persists one resumable research-state file so a long run
survives context compaction and continuation agents. The agent is the
orchestrator: this script never searches, never fetches, and never
writes report content. For the actual research workflow, see
reference/methodology.md; for the evidence substrate, see
scripts/citation_manager.py and scripts/evidence_store.py.

Phases and modes follow SKILL.md's workflow table and
reference/methodology.md: SCOPE, PLAN, RETRIEVE, TRIANGULATE, OUTLINE
REFINEMENT (4.5, standard/deep/ultradeep only), SYNTHESIZE, CRITIQUE,
REFINE, PACKAGE. quick = scope, retrieve, package; standard adds plan,
triangulate, outline refinement and synthesize; deep and ultradeep run
every phase.

State lives in the run folder: research_state.json next to
sources.jsonl, evidence.jsonl and run_manifest.json. The run folder is
--dir when given, else ~/Documents/[Topic]_Research_[YYYYMMDD]/ (the
skill's documented output root). No harness-specific home path is read
or written.

CLI:
  python3 scripts/research_engine.py --query "..." [--mode standard] [--dir RUN]
      Initialize a run (or continue one whose research_state.json
      already exists in RUN) and display the next pending phase.
  python3 scripts/research_engine.py --resume RUN/research_state.json
      Display the next pending phase of a saved run; query and mode
      come from the state file, not the command line.
  --all displays every pending phase in order (the original one-shot
      behaviour) instead of just the next one.

Exit codes: 0 phases displayed (or none left to display); 1 state-file
or run-folder error (missing file, invalid JSON, unknown phase, write
failure); 2 command-line usage errors (argparse convention).
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

STATE_FILENAME = 'research_state.json'
STATE_VERSION = '2.0'
DEFAULT_OUTPUT_ROOT = Path.home() / 'Documents'


class ResearchPhase(Enum):
    """Research pipeline phases, in methodology.md order."""
    SCOPE = 'scope'
    PLAN = 'plan'
    RETRIEVE = 'retrieve'
    TRIANGULATE = 'triangulate'
    OUTLINE_REFINEMENT = 'outline_refinement'
    SYNTHESIZE = 'synthesize'
    CRITIQUE = 'critique'
    REFINE = 'refine'
    PACKAGE = 'package'


class ResearchMode(Enum):
    """Research depth modes."""
    QUICK = 'quick'
    STANDARD = 'standard'
    DEEP = 'deep'
    ULTRADEEP = 'ultradeep'


MODE_PHASES: Dict[ResearchMode, List[ResearchPhase]] = {
    ResearchMode.QUICK: [
        ResearchPhase.SCOPE,
        ResearchPhase.RETRIEVE,
        ResearchPhase.PACKAGE,
    ],
    ResearchMode.STANDARD: [
        ResearchPhase.SCOPE,
        ResearchPhase.PLAN,
        ResearchPhase.RETRIEVE,
        ResearchPhase.TRIANGULATE,
        ResearchPhase.OUTLINE_REFINEMENT,
        ResearchPhase.SYNTHESIZE,
        ResearchPhase.PACKAGE,
    ],
    ResearchMode.DEEP: list(ResearchPhase),
    ResearchMode.ULTRADEEP: list(ResearchPhase),
}


@dataclass
class Source:
    """A research source recorded in the run state.

    The registry of record is sources.jsonl via citation_manager.py;
    these entries are the scaffold's own notebook."""
    url: str
    title: str
    snippet: str = ''
    retrieved_at: str = ''
    credibility_score: float = 0.0
    source_type: str = 'web'
    verification_status: str = 'unverified'


@dataclass
class ResearchState:
    """Research state persisted across phases and sessions.

    The CLI maintains query, mode, phase and the per-phase display
    records; the accumulator fields (scope, plan, sources, findings,
    synthesis, critique, report, metadata) are forward structure the
    orchestrating agent may fill as the run progresses."""
    query: str
    mode: ResearchMode
    phase: str
    run_dir: str
    created_at: str
    updated_at: str
    phases: List[Dict[str, Any]] = field(default_factory=list)
    scope: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    sources: List[Source] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    synthesis: Dict[str, Any] = field(default_factory=dict)
    critique: Dict[str, Any] = field(default_factory=dict)
    report: str = ''
    metadata: Dict[str, Any] = field(default_factory=dict)

    def pending_phases(self) -> List[ResearchPhase]:
        return [ResearchPhase(p['phase']) for p in self.phases
                if p.get('status') != 'displayed']

    def mark_displayed(self, phase: ResearchPhase) -> None:
        for record in self.phases:
            if record['phase'] == phase.value:
                record['status'] = 'displayed'
                record['displayed_at'] = datetime.now().isoformat()
        self.phase = phase.value

    def save(self, filepath: Path) -> None:
        self.updated_at = datetime.now().isoformat()
        payload = self.to_dict()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(filepath.parent),
                                   prefix=STATE_FILENAME + '.',
                                   suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(payload, f, indent=2)
            # mkstemp creates the temp file 0600; chmod it to what a plain
            # open() gives the run's other files (0o666 & ~umask) so the
            # state file's permissions match the run folder.
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(tmp, 0o666 & ~mask)
            os.replace(tmp, filepath)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def to_dict(self) -> Dict[str, Any]:
        return {
            'version': STATE_VERSION,
            'query': self.query,
            'mode': self.mode.value,
            'phase': self.phase,
            'run_dir': self.run_dir,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'phases': self.phases,
            'scope': self.scope,
            'plan': self.plan,
            'sources': [asdict(s) for s in self.sources],
            'findings': self.findings,
            'synthesis': self.synthesis,
            'critique': self.critique,
            'report': self.report,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], run_dir: str) -> 'ResearchState':
        phases = list(data.get('phases', []))
        for record in phases:
            try:
                ResearchPhase(record['phase'])
            except (KeyError, ValueError) as e:
                raise ValueError(f'unknown phase in state: {e}')
        return cls(
            query=data['query'],
            mode=ResearchMode(data['mode']),
            phase=data['phase'],
            run_dir=run_dir,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            phases=phases,
            scope=dict(data.get('scope', {})),
            plan=dict(data.get('plan', {})),
            sources=[Source(**s) for s in data.get('sources', [])],
            findings=list(data.get('findings', [])),
            synthesis=dict(data.get('synthesis', {})),
            critique=dict(data.get('critique', {})),
            report=data.get('report', ''),
            metadata=dict(data.get('metadata', {})),
        )

    @classmethod
    def load(cls, filepath: Path) -> 'ResearchState':
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f'Invalid state file {filepath}: {e}')
        return cls.from_dict(data, run_dir=str(filepath.parent))


def default_run_dir(query: str) -> Path:
    """The skill's documented output root: ~/Documents/[Topic]_Research_[date]."""
    topic = re.sub(r'[^a-z0-9]+', '_', query.lower()).strip('_')
    topic = topic[:40].strip('_') or 'Research'
    topic = topic[0].upper() + topic[1:]
    stamp = datetime.now().strftime('%Y%m%d')
    return DEFAULT_OUTPUT_ROOT / f'{topic}_Research_{stamp}'


PHASE_INSTRUCTIONS: Dict[ResearchPhase, str] = {
    ResearchPhase.SCOPE: """# Phase 1: SCOPE — Research Framing

Full methodology: reference/methodology.md (Phase 1).

Your task: define research boundaries and success criteria.

1. Decompose the question into 3-5 core components
2. Identify 2-4 stakeholder perspectives
3. Define what is IN scope and what is OUT of scope
4. List 3-5 success criteria
5. Document 3-5 assumptions that need validation

Comprehensive runs also record which facets of the topic are actively
disputed in run_manifest.json -> contested_facets ([] is an auditable
position, not a skipped question; non-empty loads
references/contested-topics.md).

Use extended reasoning to explore multiple framings before committing
to a scope.""",

    ResearchPhase.PLAN: """# Phase 2: PLAN — Strategy Formulation

Full methodology: reference/methodology.md (Phase 2).

Your task: create the research roadmap.

1. Identify 5-10 primary sources and 5-10 secondary/backup sources
2. Map knowledge dependencies (what must be understood first)
3. Create 10-15 search query variations
4. Plan the triangulation approach
5. Define 3-5 quality gates

Branch into 3-4 potential research paths, evaluate, then converge on
the optimal strategy.""",

    ResearchPhase.RETRIEVE: """# Phase 3: RETRIEVE — Parallel Information Gathering

Full methodology: reference/methodology.md (Phase 3).

Step 0: get the current date before any search (Bash: date +%Y-%m-%d)
and use that year for date-filtered queries and recency checks.

Decompose the question into 5-10 independent search angles, then launch
all searches in parallel:

- Primary: search-cli, run via the shell (search "query" --json -c 10;
  -m academic / news / scholar for domain search, -m extract for pages)
- Fallback: the harness's built-in web search tool
- Spawn 3-5 parallel deep-dive subagents for papers, documentation and
  specialized domains; require structured evidence objects back, not
  free text

Persist evidence as it arrives, never only in context:

  python3 scripts/citation_manager.py register-source --json '{"raw_url": "...", "title": "..."}' --dir [folder]
  python3 scripts/evidence_store.py add --json '{"source_id": "...", "quote": "exact text", "evidence_type": "direct_quote", "locator": "page 5"}' --dir [folder]

First Finish Search threshold to proceed to Phase 4:
quick 10+ sources avg credibility >60 (or 2 min); standard 15+ >60
(or 5 min); deep 25+ >70 (or 10 min); ultradeep 30+ >75 (or 15 min).
Keep source diversity (3+ source types, mixed recency, competing
perspectives).""",

    ResearchPhase.TRIANGULATE: """# Phase 4: TRIANGULATE — Cross-Reference Verification

Full methodology: reference/methodology.md (Phase 4).

Your task: validate information across independent sources.

1. List the major claims from retrieval
2. Cross-reference each core claim across 3+ independent sources
3. Flag single-source claims as "unverified"
4. Score credibility with scripts/source_evaluator.py; flag sources
   under 40 for extra verification
5. Document contradictions, consensus areas and debate areas
6. Record verification status per claim""",

    ResearchPhase.OUTLINE_REFINEMENT: """# Phase 4.5: OUTLINE REFINEMENT — Dynamic Evolution

Full methodology: reference/methodology.md (Phase 4.5). Runs in
standard, deep and ultradeep modes only; quick skips it.

Your task: adapt the research direction to the evidence found.

1. Compare the Phase 1 scope against Phase 3-4 discoveries
2. Decide whether the outline needs adaptation: major findings that
   contradict assumptions, a critical subtopic that emerged, or a
   question that proved too broad or narrow all trigger refinement
3. If refining: add sections for unexpected but important findings,
   demote thin ones, reorder by evidence strength — never restructure
   more than 50%, and never add sections without evidence in hand
4. Fill critical gaps with 2-3 targeted searches, time-boxed to 2-5
   minutes
5. Document what changed and why (evidence-driven reasons) for the
   methodology appendix""",

    ResearchPhase.SYNTHESIZE: """# Phase 5: SYNTHESIZE — Deep Analysis

Full methodology: reference/methodology.md (Phase 5).

Your task: connect insights and generate novel understanding.

1. Identify 5-10 key patterns across sources
2. Map relationships between concepts
3. Generate 3-5 insights that go beyond the source material
4. Build conceptual frameworks and argument structures
5. Develop evidence hierarchies

Use extended reasoning to explore non-obvious connections and
second-order implications, including what the sources might be
missing.""",

    ResearchPhase.CRITIQUE: """# Phase 6: CRITIQUE — Quality Assurance

Full methodology: reference/methodology.md (Phase 6).

Your task: rigorously evaluate research quality.

Red team the work: logical consistency, citation completeness, gaps,
balance, and alternative interpretations. Ask what is missing, what
could be wrong, what a skeptic would say.

Deep and ultradeep modes add persona-based critique (2-3 personas):
Skeptical Practitioner, Adversarial Reviewer, Implementation Engineer.

Critical gap loop-back: if critique finds a critical knowledge gap
(not a writing issue), return to retrieval with targeted delta-queries,
time-boxed to 3-5 minutes, before proceeding.""",

    ResearchPhase.REFINE: """# Phase 7: REFINE — Iterative Improvement

Full methodology: reference/methodology.md (Phase 7).

Your task: address gaps and strengthen weak areas.

1. Conduct additional research for the gaps critique identified
2. Strengthen weak arguments with more evidence
3. Add missing perspectives
4. Resolve contradictions where possible
5. Enhance clarity; verify all revised content""",

    ResearchPhase.PACKAGE: """# Phase 8: PACKAGE — Report Generation

Full methodology: reference/report-assembly.md; format choice per
references/format-selection.md.

Your task: deliver the professional, actionable research report.

1. Choose the format (quick-brief / comparison / research-summary /
   comprehensive-report / discovery-catalog) and follow its template
2. Assemble progressively per reference/report-assembly.md; every
   factual claim cites [N] with evidence backing in evidence.jsonl
3. Write all artifacts to the run folder (report, sources.jsonl,
   evidence.jsonl, claims.jsonl, run_manifest.json)
4. Number citations and verify claims:
   python3 scripts/citation_manager.py assign-display-numbers --dir [folder]
   python3 scripts/extract_claims.py extract --report [report.md] --dir [folder]
   python3 scripts/verify_claim_support.py link --dir [folder]
   python3 scripts/citation_manager.py renumber-report --dir [folder]
   python3 scripts/citation_manager.py export-bibliography --dir [folder] --style markdown
5. Run the Phase 8 gate chain on the assembled report — the ordered
   python3 commands in reference/quality-gates.md#phase-8-gate-chain
   (claim support, numbering, validation, readability, render, theme QA)
6. Reports over 18,000 words follow reference/continuation.md""",
}


class ResearchEngine:
    """Displays phase instructions and maintains the run state file."""

    def __init__(self, state: ResearchState, state_path: Path):
        self.state = state
        self.state_path = state_path

    @classmethod
    def init_run(cls, query: str, mode: ResearchMode, run_dir: Path) -> 'ResearchEngine':
        now = datetime.now().isoformat()
        phases = [{'phase': p.value, 'status': 'pending', 'displayed_at': None}
                  for p in MODE_PHASES[mode]]
        state = ResearchState(
            query=query,
            mode=mode,
            phase=MODE_PHASES[mode][0].value,
            run_dir=str(run_dir),
            created_at=now,
            updated_at=now,
            phases=phases,
            metadata={'started_at': now},
        )
        return cls(state, run_dir / STATE_FILENAME)

    @classmethod
    def open_run(cls, state_path: Path) -> 'ResearchEngine':
        state = ResearchState.load(state_path)
        return cls(state, state_path)

    def display_next(self) -> bool:
        """Display the next pending phase; False when none remain."""
        pending = self.state.pending_phases()
        if not pending:
            return False
        self._display(pending[0])
        return True

    def display_all(self) -> int:
        """Display every pending phase in order; returns the count."""
        count = 0
        while self.display_next():
            count += 1
        return count

    def _display(self, phase: ResearchPhase) -> None:
        total = len(self.state.phases)
        index = next(i for i, p in enumerate(self.state.phases, start=1)
                     if p['phase'] == phase.value)
        print('=' * 72)
        print(f'PHASE {index}/{total}: {phase.value.upper()}')
        print('=' * 72)
        print(PHASE_INSTRUCTIONS.get(
            phase, f'No instructions for phase {phase.value}; '
                   f'see reference/methodology.md'))
        self.state.mark_displayed(phase)
        self.state.save(self.state_path)
        print(f'\nState saved to: {self.state_path}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Research run state scaffold: displays the phase '
                    'instructions for the selected mode and persists a '
                    'resumable state file in the run folder.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/research_engine.py --query "state of quantum computing" --mode deep
  python3 scripts/research_engine.py -q "PostgreSQL vs Supabase" -m standard --dir ~/Documents/PG_Research_20261119
  python3 scripts/research_engine.py --resume ~/Documents/PG_Research_20261119/research_state.json
  python3 scripts/research_engine.py --resume RUN/research_state.json --all
        """,
    )
    parser.add_argument('--query', '-q', type=str, default=None,
                        help='research question (required unless --resume)')
    parser.add_argument('--mode', '-m', type=str,
                        choices=[m.value for m in ResearchMode],
                        default=None,
                        help='research depth mode (default: standard; '
                             'ignored when resuming — the state file wins)')
    parser.add_argument('--dir', '-d', type=str, default=None,
                        help='run folder for the state file (default: '
                             '~/Documents/[Topic]_Research_[YYYYMMDD]/)')
    parser.add_argument('--resume', type=str, default=None,
                        help='path to an existing research_state.json')
    parser.add_argument('--all', action='store_true',
                        help='display every pending phase in order '
                             'instead of only the next one')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.resume:
        state_path = Path(args.resume).expanduser()
        if not state_path.is_file():
            print(f'Error: state file not found: {state_path}', file=sys.stderr)
            return 1
        try:
            engine = ResearchEngine.open_run(state_path)
        except (ValueError, KeyError, TypeError) as e:
            print(f'Error: invalid state file {state_path}: {e}', file=sys.stderr)
            return 1
        if args.query and args.query != engine.state.query:
            print('Note: --query ignored; the resumed run keeps its own query.',
                  file=sys.stderr)
        if args.mode and args.mode != engine.state.mode.value:
            print(f'Note: --mode ignored; the resumed run keeps its mode '
                  f'({engine.state.mode.value}).', file=sys.stderr)
    else:
        if not args.query:
            parser.error('--query is required unless --resume names a state file')
        mode = ResearchMode(args.mode or 'standard')
        run_dir = (Path(args.dir).expanduser() if args.dir
                   else default_run_dir(args.query))
        state_path = run_dir / STATE_FILENAME
        if state_path.exists():
            print(f'Resuming existing run in {run_dir} ({STATE_FILENAME} found).',
                  file=sys.stderr)
            try:
                engine = ResearchEngine.open_run(state_path)
            except (ValueError, KeyError, TypeError) as e:
                print(f'Error: invalid state file {state_path}: {e}',
                      file=sys.stderr)
                return 1
            if args.mode and args.mode != engine.state.mode.value:
                print(f'Note: --mode ignored; the existing run keeps its mode '
                      f'({engine.state.mode.value}).', file=sys.stderr)
        else:
            engine = ResearchEngine.init_run(args.query, mode, run_dir)

    print(f'Research run: {engine.state.query}')
    print(f'Mode: {engine.state.mode.value} | State: {engine.state_path}')

    try:
        if args.all:
            shown = engine.display_all()
            if shown == 0:
                print(f'All {len(engine.state.phases)} phases of this '
                      f'{engine.state.mode.value} run are already displayed.')
            return 0

        if not engine.display_next():
            print(f'All {len(engine.state.phases)} phases of this '
                  f'{engine.state.mode.value} run are already displayed. '
                  f'State: {engine.state_path}')
    except OSError as e:
        print(f'Error: cannot write state file {engine.state_path}: {e}',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
