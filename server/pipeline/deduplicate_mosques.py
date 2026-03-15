"""
Mosque Deduplication
====================
Finds and merges duplicate mosque entries caused by OSM having the same
physical mosque tagged as both a node and a way/relation.

See docs/SCRAPING_PIPELINE.md — "Mosque Deduplication" for the full design.

Usage:
    python -m pipeline.deduplicate_mosques
    python -m pipeline.deduplicate_mosques --dry-run
    python -m pipeline.deduplicate_mosques --review   # also show borderline pairs
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

MERGE_DISTANCE_M = 50       # auto-merge within this distance
REVIEW_DISTANCE_M = 200     # flag for review up to this distance
NAME_SIM_THRESHOLD = 0.6    # pg_trgm similarity for auto-merge
REVIEW_SIM_THRESHOLD = 0.85 # pg_trgm similarity for borderline review


@dataclass
class MosquePair:
    id1: str
    id2: str
    name1: str
    name2: str
    osm_id1: Optional[str]
    osm_id2: Optional[str]
    dist_m: float
    name_similarity: float
    fields1: int  # non-null field count
    fields2: int
    has_website1: bool
    has_website2: bool
    created1: str
    created2: str


def get_sync_engine():
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).split("?")[0]  # strip query params like ssl=
    return create_engine(db_url, echo=False)


def count_fields(row: dict) -> int:
    """Count non-null useful fields for winner selection."""
    fields = ["name", "website", "phone", "address", "city", "state", "email",
              "denomination", "timezone"]
    score = sum(1 for f in fields if row.get(f) and row[f] != "Unknown Mosque")
    return score


def pick_winner(p: MosquePair, row1: dict, row2: dict) -> tuple[str, str]:
    """
    Returns (winner_id, loser_id).
    Rules (first applicable wins):
    1. Named beats "Unknown Mosque"
    2. More complete data wins
    3. Has website wins
    4. Older record wins
    """
    unknown1 = row1["name"] in ("Unknown Mosque", None, "")
    unknown2 = row2["name"] in ("Unknown Mosque", None, "")

    if unknown1 and not unknown2:
        return p.id2, p.id1
    if unknown2 and not unknown1:
        return p.id1, p.id2

    if p.fields1 > p.fields2:
        return p.id1, p.id2
    if p.fields2 > p.fields1:
        return p.id2, p.id1

    if p.has_website1 and not p.has_website2:
        return p.id1, p.id2
    if p.has_website2 and not p.has_website1:
        return p.id2, p.id1

    # Tiebreaker: older record
    if p.created1 <= p.created2:
        return p.id1, p.id2
    return p.id2, p.id1


def merge_fields(session: Session, winner_id: str, loser_id: str, dry_run: bool):
    """Copy any non-null fields from loser that winner is missing."""
    mergeable = ["website", "phone", "address", "city", "state", "zip",
                 "email", "denomination", "capacity", "has_womens_section",
                 "has_parking", "wheelchair_accessible", "name_arabic",
                 "islamicfinder_id", "google_place_id"]

    for field in mergeable:
        session.execute(text(f"""
            UPDATE mosques
            SET {field} = COALESCE({field}, (SELECT {field} FROM mosques WHERE id = :loser_id))
            WHERE id = :winner_id AND {field} IS NULL
        """), {"winner_id": winner_id, "loser_id": loser_id})


def find_duplicate_pairs(session: Session, max_dist: float) -> list[MosquePair]:
    """Find all mosque pairs within max_dist metres using PostGIS + pg_trgm."""
    result = session.execute(text("""
        SELECT
            m1.id::text      AS id1,
            m2.id::text      AS id2,
            m1.name          AS name1,
            m2.name          AS name2,
            m1.osm_id        AS osm_id1,
            m2.osm_id        AS osm_id2,
            round(ST_Distance(m1.geom::geography, m2.geom::geography)::numeric, 1) AS dist_m,
            round(similarity(
                LOWER(COALESCE(m1.name, '')),
                LOWER(COALESCE(m2.name, ''))
            )::numeric, 3)   AS name_sim,
            (CASE WHEN m1.name IS NOT NULL AND m1.name != 'Unknown Mosque' THEN 1 ELSE 0 END
             + CASE WHEN m1.website IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m1.phone IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m1.address IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m1.city IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m1.state IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m1.email IS NOT NULL THEN 1 ELSE 0 END)  AS fields1,
            (CASE WHEN m2.name IS NOT NULL AND m2.name != 'Unknown Mosque' THEN 1 ELSE 0 END
             + CASE WHEN m2.website IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m2.phone IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m2.address IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m2.city IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m2.state IS NOT NULL THEN 1 ELSE 0 END
             + CASE WHEN m2.email IS NOT NULL THEN 1 ELSE 0 END)  AS fields2,
            (m1.website IS NOT NULL) AS has_website1,
            (m2.website IS NOT NULL) AS has_website2,
            m1.created_at::text AS created1,
            m2.created_at::text AS created2
        FROM mosques m1
        JOIN mosques m2 ON m1.id < m2.id
        WHERE
            m1.is_active = true AND m2.is_active = true
            AND ST_DWithin(m1.geom::geography, m2.geom::geography, :max_dist)
        ORDER BY dist_m ASC
    """), {"max_dist": max_dist})

    pairs = []
    for row in result.mappings():
        pairs.append(MosquePair(
            id1=row["id1"], id2=row["id2"],
            name1=row["name1"] or "Unknown Mosque",
            name2=row["name2"] or "Unknown Mosque",
            osm_id1=row["osm_id1"], osm_id2=row["osm_id2"],
            dist_m=float(row["dist_m"]),
            name_similarity=float(row["name_sim"]),
            fields1=row["fields1"], fields2=row["fields2"],
            has_website1=row["has_website1"],
            has_website2=row["has_website2"],
            created1=row["created1"], created2=row["created2"],
        ))
    return pairs


def is_auto_merge(p: MosquePair) -> bool:
    """True if this pair should be auto-merged."""
    if p.dist_m > MERGE_DISTANCE_M:
        return False
    # Same name, one unknown, or high similarity
    if p.name1 == p.name2:
        return True
    if p.name1 == "Unknown Mosque" or p.name2 == "Unknown Mosque":
        return True
    return p.name_similarity >= NAME_SIM_THRESHOLD


def is_borderline(p: MosquePair) -> bool:
    """True if this pair should be flagged for manual review."""
    if p.dist_m <= MERGE_DISTANCE_M:
        return False  # already auto-merged
    return p.dist_m <= REVIEW_DISTANCE_M and p.name_similarity >= REVIEW_SIM_THRESHOLD


def run_deduplication(dry_run: bool = False, show_review: bool = False) -> dict:
    engine = get_sync_engine()
    stats = {"scanned": 0, "merged": 0, "skipped": 0, "borderline": 0}

    with Session(engine) as session:
        all_pairs = find_duplicate_pairs(session, REVIEW_DISTANCE_M)
        stats["scanned"] = len(all_pairs)

        for p in all_pairs:
            if is_auto_merge(p):
                row1 = session.execute(
                    text("SELECT * FROM mosques WHERE id = :id"), {"id": p.id1}
                ).mappings().first()
                row2 = session.execute(
                    text("SELECT * FROM mosques WHERE id = :id"), {"id": p.id2}
                ).mappings().first()

                if not row1 or not row2:
                    stats["skipped"] += 1
                    continue

                winner_id, loser_id = pick_winner(p, dict(row1), dict(row2))
                winner_name = p.name1 if winner_id == p.id1 else p.name2
                loser_name  = p.name2 if winner_id == p.id1 else p.name1

                logger.info(
                    f"MERGE  {p.dist_m}m  sim={p.name_similarity:.2f}"
                    f"  KEEP: '{winner_name}'"
                    f"  DROP: '{loser_name}'"
                )

                if not dry_run:
                    merge_fields(session, winner_id, loser_id, dry_run)
                    session.execute(
                        text("DELETE FROM mosques WHERE id = :id"), {"id": loser_id}
                    )
                    session.commit()

                stats["merged"] += 1

            elif is_borderline(p) and show_review:
                logger.warning(
                    f"REVIEW {p.dist_m}m  sim={p.name_similarity:.2f}"
                    f"  '{p.name1}'  vs  '{p.name2}'"
                )
                stats["borderline"] += 1

            else:
                stats["skipped"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Deduplicate mosque database entries")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--review", action="store_true", help="Also show borderline pairs")
    args = parser.parse_args()

    logger.info(f"Running mosque deduplication {'(DRY RUN) ' if args.dry_run else ''}...")
    stats = run_deduplication(dry_run=args.dry_run, show_review=args.review)

    logger.info("=" * 50)
    logger.info(f"Pairs scanned:  {stats['scanned']}")
    logger.info(f"Merged:         {stats['merged']}")
    logger.info(f"Borderline:     {stats['borderline']}")
    logger.info(f"Kept as-is:     {stats['skipped']}")
    if args.dry_run:
        logger.info("(dry run — no changes written)")


if __name__ == "__main__":
    main()
