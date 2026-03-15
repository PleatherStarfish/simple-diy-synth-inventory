"""
BOM Matching Service
Matches normalized BOM items to inventory parts using fuzzy search.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.search import SearchService

logger = logging.getLogger(__name__)

AUTO_MATCH_THRESHOLD = 80.0


@dataclass(slots=True)
class ScoredMatch:
    part_id: int
    score: float
    reason: str


class BomMatchingService:
    def __init__(self, search_service: SearchService, part_repo: PartRepository) -> None:
        self.search_service = search_service
        self.part_repo = part_repo

    def find_candidates(
        self,
        normalized_value: str,
        component_type: str | None = None,
        package_hint: str | None = None,
        limit: int = 10,
    ) -> list[ScoredMatch]:
        """Find inventory parts matching a normalized BOM value."""
        scored = self.search_service.search_scored(normalized_value, limit=limit * 2)
        if not scored:
            return []

        results: list[ScoredMatch] = []
        for part_id, score in scored:
            part = self.part_repo.get_part_by_id(part_id)
            if part is None:
                continue

            reason_parts = [f"name match ({score:.0f})"]

            # Boost score if category aligns with component_type
            if component_type and part.category:
                cat_lower = part.category.lower()
                type_lower = component_type.lower()
                if type_lower in cat_lower or cat_lower in type_lower:
                    score += 10
                    reason_parts.append("category match")

            # Boost score if package matches
            if package_hint and part.default_package:
                pkg_lower = part.default_package.lower()
                hint_lower = package_hint.lower()
                if hint_lower in pkg_lower or pkg_lower in hint_lower:
                    score += 5
                    reason_parts.append("package match")

            results.append(ScoredMatch(
                part_id=part_id,
                score=score,
                reason=", ".join(reason_parts),
            ))

        results.sort(key=lambda m: -m.score)
        return results[:limit]

    def auto_match_bom(self, bom_source_id: int, bom_repo: BomRepository) -> int:
        """Run auto-matching on all unmatched items for a BOM source. Returns count matched."""
        unmatched = bom_repo.list_unmatched_items(bom_source_id)
        matched_count = 0

        for item in unmatched:
            candidates = self.find_candidates(
                item.normalized_value,
                item.component_type,
                item.package_hint,
                limit=1,
            )
            if candidates and candidates[0].score >= AUTO_MATCH_THRESHOLD:
                best = candidates[0]
                bom_repo.link_to_part(
                    item.id,
                    part_id=best.part_id,
                    confidence=best.score / 100.0,
                    status="auto_matched",
                )
                matched_count += 1
                logger.debug(
                    "Auto-matched '%s' -> part_id=%d (score=%.1f)",
                    item.normalized_value, best.part_id, best.score,
                )

        logger.info(
            "Auto-matched %d/%d items for source %d",
            matched_count, len(unmatched), bom_source_id,
        )
        return matched_count

    def auto_match_item(self, item_id: int, bom_repo: BomRepository) -> ScoredMatch | None:
        """Re-run matching on a single item. Returns match if found."""
        item = bom_repo.get_normalized_item(item_id)
        if item is None:
            return None

        candidates = self.find_candidates(
            item.normalized_value,
            item.component_type,
            item.package_hint,
            limit=1,
        )
        if candidates and candidates[0].score >= AUTO_MATCH_THRESHOLD:
            best = candidates[0]
            bom_repo.link_to_part(
                item_id,
                part_id=best.part_id,
                confidence=best.score / 100.0,
                status="auto_matched",
            )
            return best
        return None
