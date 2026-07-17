"""Corpus manifest — the single source of truth for what is (and is not) indexed.

13 books are included with canonical titles. The 14th, Beck's *Cognitive Therapy
of Depression*, had a broken 876-character PDF extraction and has NO usable text:
it is listed here as EXCLUDED and must WARN loudly at every index build. It must
never be silently indexed, and Dr. Alex must never pretend to cite it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BOOKS_DIR_ENV = "DR_ALEX_BOOKS_DIR"
DEFAULT_CORPUS_DIR = Path(
    "/Users/prax/agent-memory-staging/claude-export/dr-alex-books"
)


@dataclass(frozen=True)
class BookSpec:
    slug: str
    title: str
    short_title: str
    authors: str
    filename: str | None
    included: bool = True
    exclusion_reason: str | None = None


_BOOKS: tuple[BookSpec, ...] = (
    BookSpec(
        slug="feeling-good",
        title="Feeling Good: The New Mood Therapy",
        short_title="Feeling Good",
        authors="David D. Burns",
        filename="feeling-good-the-new-mood-therapy-david-d-burns-pd.txt",
    ),
    BookSpec(
        slug="dbt-skills-workbook",
        title="The Dialectical Behavior Therapy Skills Workbook, 2nd Edition",
        short_title="DBT Skills Workbook",
        authors="Matthew McKay, Jeffrey C. Wood, Jeffrey Brantley",
        filename="the-dialectical-behavior-therapy-skills-workbook-2.txt",
    ),
    BookSpec(
        slug="mindful-way",
        title="The Mindful Way through Depression: Freeing Yourself from Chronic Unhappiness",
        short_title="The Mindful Way through Depression",
        authors="Mark Williams, John Teasdale, Zindel Segal, Jon Kabat-Zinn",
        filename="the-mindful-way-through-depression-freeing-yoursel.txt",
    ),
    BookSpec(
        slug="anxiety-phobia-workbook",
        title="The Anxiety and Phobia Workbook",
        short_title="The Anxiety and Phobia Workbook",
        authors="Edmund J. Bourne",
        filename="the-anxiety-and-phobia-workbook-edmund-j-bourne-pd.txt",
    ),
    BookSpec(
        slug="adhd-2-0",
        title="ADHD 2.0",
        short_title="ADHD 2.0",
        authors="Edward M. Hallowell, John J. Ratey",
        filename="adhd-2-0-edward-m-hallowell-m-d-john-j-ratey-etc-p.txt",
    ),
    BookSpec(
        slug="atomic-habits",
        title="Atomic Habits: Tiny Changes, Remarkable Results",
        short_title="Atomic Habits",
        authors="James Clear",
        filename="atomic-habits-tiny-changes-remarkable-results-jame.txt",
    ),
    BookSpec(
        slug="how-to-adhd",
        title="How to ADHD: An Insider's Guide to Working with Your Brain (Not Against It)",
        short_title="How to ADHD",
        authors="Jessica McCabe",
        filename="how-to-adhd-an-insiders-guide-to-working-with-your.txt",
    ),
    BookSpec(
        slug="self-compassion",
        title="Self-Compassion",
        short_title="Self-Compassion",
        authors="Kristin Neff",
        filename="self-compassion-dr-kristin-neff-pdf.txt",
    ),
    BookSpec(
        slug="taking-charge-adult-adhd",
        title="Taking Charge of Adult ADHD, 2nd Edition",
        short_title="Taking Charge of Adult ADHD",
        authors="Russell A. Barkley, Christine M. Benton",
        filename="taking-charge-of-adult-adhd-proven-strategies-to-s.txt",
    ),
    BookSpec(
        slug="procrastination-equation",
        title="The Procrastination Equation",
        short_title="The Procrastination Equation",
        authors="Piers Steel",
        filename="the-procrastination-equation-ph-d-piers-steel-pdf.txt",
    ),
    BookSpec(
        slug="driven-to-distraction",
        title="Driven to Distraction (Revised): Recognizing and Coping with Attention Deficit Disorder",
        short_title="Driven to Distraction",
        authors="Edward M. Hallowell, John J. Ratey",
        filename="driven-to-distraction-revised-recognizing-and-copi.txt",
    ),
    BookSpec(
        slug="mastering-adult-adhd",
        title="Mastering Your Adult ADHD, 2nd Edition: A Cognitive-Behavioral Treatment Program (Client Workbook)",
        short_title="Mastering Your Adult ADHD",
        authors="Steven A. Safren, Susan E. Sprich, Carol A. Perlman, Michael W. Otto",
        filename="mastering-your-adult-adhd-2nd-ed-a-cognitive-behav.txt",
    ),
    BookSpec(
        slug="tiny-habits",
        title="Tiny Habits: The Small Changes That Change Everything",
        short_title="Tiny Habits",
        authors="BJ Fogg",
        filename="tiny-habits-the-small-changes-that-change-everythi.txt",
    ),
    BookSpec(
        slug="cognitive-therapy-depression",
        title="Cognitive Therapy of Depression",
        short_title="Cognitive Therapy of Depression",
        authors="Aaron T. Beck, A. John Rush, Brian F. Shaw, Gary Emery",
        filename=None,
        included=False,
        exclusion_reason=(
            "broken PDF extraction (876 chars of 14 expected books) — no usable "
            "text; must never be silently indexed or cited"
        ),
    ),
)


def all_books() -> tuple[BookSpec, ...]:
    return _BOOKS


def included_books() -> tuple[BookSpec, ...]:
    return tuple(b for b in _BOOKS if b.included)


def excluded_books() -> tuple[BookSpec, ...]:
    return tuple(b for b in _BOOKS if not b.included)


def by_slug(slug: str) -> BookSpec | None:
    for b in _BOOKS:
        if b.slug == slug:
            return b
    return None


def corpus_dir() -> Path:
    override = os.environ.get(BOOKS_DIR_ENV)
    return Path(override) if override else DEFAULT_CORPUS_DIR
