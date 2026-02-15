from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional

from app.core.database import get_db
from app.core.config import settings
from app.models.catalog import CatalogPointer
from app.models.program import Program

logger = logging.getLogger(__name__)


class CatalogService:
    _PREFILTER_MAX_SPECS = 4

    def __init__(self):
        self.db = get_db()

    def _programs_ref(self, catalog_id: str):
        return (
            self.db.collection(settings.COLLECTION_CATALOGS)
            .document(catalog_id)
            .collection(settings.COLLECTION_PROGRAMS)
        )

    def _parse_program_docs(self, docs: Iterable[Any]) -> List[Program]:
        programs: list[Program] = []
        for doc in docs:
            try:
                programs.append(Program(**doc.to_dict()))
            except Exception as e:
                print(f"Error parsing program {getattr(doc, 'id', 'unknown')}: {e}")
                continue
        return programs

    async def get_current_catalog_id(self, municipality_id: str, domain: str) -> Optional[str]:
        if not self.db:
            return None
            
        doc_id = f"{municipality_id}_{domain}"
        doc = self.db.collection(settings.COLLECTION_CATALOG_POINTERS).document(doc_id).get()
        
        if doc.exists:
            pointer = CatalogPointer(**doc.to_dict())
            return pointer.current_catalog_id
        return None

    async def get_programs(self, catalog_id: str) -> List[Program]:
        if not self.db:
            return []

        docs = self._programs_ref(catalog_id).stream()
        return self._parse_program_docs(docs)

    def _build_prefilter_specs(
        self,
        profile_flags: dict[str, Any],
    ) -> list[tuple[str, str, Any]]:
        """
        Build active prefilter specs for requires_* fields.
        Default behavior is exclusion:
        - if user flag is not True, exclude requires_* == True programs.
        - if user flag is True, do not prefilter on that field.
        """
        specs: list[tuple[str, str, Any]] = []
        if profile_flags.get("has_disability_child") is not True:
            specs.append(("eligibility_profile.requires_disability_child", "exclude_true", True))
        if profile_flags.get("is_single_parent") is not True:
            specs.append(("eligibility_profile.requires_single_parent", "exclude_true", True))
        return specs

    def _apply_requires_prefilter(
        self,
        programs: list[Program],
        profile_flags: dict[str, Any],
    ) -> list[Program]:
        """
        Search-time prefilter:
        - By default, exclude requires_disability_child / requires_single_parent programs.
        - Include them only when the corresponding user profile flag is explicitly True.
        """
        allow_disability = profile_flags.get("has_disability_child") is True
        allow_single_parent = profile_flags.get("is_single_parent") is True

        filtered: list[Program] = []
        for program in programs:
            eligibility = program.eligibility_profile
            if eligibility is None:
                filtered.append(program)
                continue

            if eligibility.requires_disability_child is True and not allow_disability:
                continue
            if eligibility.requires_single_parent is True and not allow_single_parent:
                continue
            filtered.append(program)
        return filtered

    async def get_programs_prefiltered_with_meta(
        self,
        catalog_id: str,
        profile_flags: dict[str, Any],
    ) -> dict[str, Any]:
        specs = self._build_prefilter_specs(profile_flags)
        meta: dict[str, Any] = {
            "stage": "prefilter_requires_flags",
            "prefilter_fields": [spec[0] for spec in specs],
            "specs_total": len(specs),
            "queries_executed": 0,
            "source_count": 0,
            "filtered_count": 0,
        }
        if not self.db:
            return {"programs": [], "meta": meta}

        docs = self._programs_ref(catalog_id).stream()
        all_programs = self._parse_program_docs(docs)
        meta["source_count"] = len(all_programs)
        filtered_programs = self._apply_requires_prefilter(all_programs, profile_flags)
        meta["filtered_count"] = len(filtered_programs)
        return {"programs": filtered_programs, "meta": meta}

    async def get_programs_prefiltered(
        self,
        catalog_id: str,
        profile_flags: dict[str, Any],
    ) -> List[Program]:
        """
        Narrow candidates at Firestore query-stage.
        If filtering yields no stable candidate set, caller should fallback to full fetch.
        """
        payload = await self.get_programs_prefiltered_with_meta(catalog_id, profile_flags)
        programs = payload.get("programs")
        if isinstance(programs, list):
            return programs
        return []

    async def get_latest_programs_for_profile_with_meta(
        self,
        municipality_id: str,
        domain: str,
        profile_flags: dict[str, Any],
    ) -> dict[str, Any]:
        catalog_id = await self.get_current_catalog_id(municipality_id, domain)
        if not catalog_id:
            return {
                "programs": [],
                "meta": {
                    "stage": "missing_catalog",
                    "catalog_id": "",
                    "returned_count": 0,
                },
            }

        payload = await self.get_programs_prefiltered_with_meta(catalog_id, profile_flags)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        programs = payload.get("programs") if isinstance(payload.get("programs"), list) else []
        normalized_meta = {
            **meta,
            "catalog_id": catalog_id,
            "returned_count": len(programs),
        }
        return {"programs": programs, "meta": normalized_meta}

    async def get_latest_programs_for_profile(
        self,
        municipality_id: str,
        domain: str,
        profile_flags: dict[str, Any],
    ) -> List[Program]:
        payload = await self.get_latest_programs_for_profile_with_meta(
            municipality_id=municipality_id,
            domain=domain,
            profile_flags=profile_flags,
        )
        programs = payload.get("programs")
        if isinstance(programs, list):
            return programs
        return []

    async def get_latest_programs(self, municipality_id: str, domain: str) -> List[Program]:
        catalog_id = await self.get_current_catalog_id(municipality_id, domain)
        if not catalog_id:
            return []
        
        return await self.get_programs(catalog_id)
