import argparse
import asyncio
import sys
import os
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Ensure backend root is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

from app.batch.jobs.collector import CollectorJob
from app.batch.jobs.deduper import DeduperJob
from app.batch.jobs.structurer import StructurerJob
from app.batch.targets import (
    DEFAULT_TARGETS_FILE,
    load_targets_file,
    resolve_target,
    resolve_engine_ids,
)
from app.core.database import get_db
from app.core.config import settings
from app.models.catalog import Catalog, CatalogStatus, BatchStage

async def create_catalog(
    municipality_id: str, domain: str, municipality_name: str | None = None
) -> str:
    db = get_db()
    catalog_id = str(uuid.uuid4())
    catalog = Catalog(
        id=catalog_id,
        municipality_id=municipality_id,
        municipality_name=municipality_name,
        domain=domain,
        status=CatalogStatus.BUILDING,
        stage=BatchStage.COLLECTING,
        build_started_at=datetime.now()
    )
    db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).set(catalog.model_dump())
    print(f"Created new Catalog: {catalog_id}")
    return catalog_id


def resolve_municipality_name(
    municipality_id: str,
    fallback_name: str | None = None,
    db=None,
) -> str:
    if db:
        doc = db.collection(settings.COLLECTION_MUNICIPALITIES).document(municipality_id).get()
        if doc.exists:
            name = doc.to_dict().get("name")
            if name:
                return name
    return fallback_name or "Unknown"


async def main():
    parser = argparse.ArgumentParser(description="Gov-Alternate Batch Processor")
    parser.add_argument(
        "--job",
        type=str,
        required=True,
        choices=["collector", "deduper", "structurer", "pipeline"],
        help="Job type",
    )
    parser.add_argument(
        "--municipality_id",
        type=str,
        required=False,
        help="Municipality ID (e.g. tokyo-chiyoda). If omitted for collector, runs all targets.",
    )
    parser.add_argument("--domain", type=str, default="moving", choices=["moving", "childcare"], help="Domain")
    parser.add_argument("--catalog_id", type=str, help="Catalog ID (Required for deduper/structurer)")
    
    # Optional Name (For collector convenience)
    parser.add_argument("--municipality_name", type=str, help="Municipality Name (e.g. 千代田区)")
    parser.add_argument(
        "--targets_file",
        type=str,
        default=str(DEFAULT_TARGETS_FILE),
        help="Batch targets JSON file",
    )
    parser.add_argument(
        "--batch_all",
        action="store_true",
        help="Run collector/pipeline for all targets in targets_file (optional if municipality_id is omitted)",
    )

    args = parser.parse_args()

    # Validate
    if args.job in ["deduper", "structurer"] and not args.catalog_id:
        print(f"Error: --catalog_id is required for {args.job}")
        return
    if args.job in ["deduper", "structurer"] and not args.municipality_id:
        print(f"Error: --municipality_id is required for {args.job}")
        return

    targets_data = None
    targets_path = Path(args.targets_file) if args.targets_file else None
    if targets_path and targets_path.exists():
        try:
            targets_data = load_targets_file(targets_path)
        except Exception as e:
            print(f"Warning: failed to load targets file '{targets_path}': {e}")

    catalog_id = args.catalog_id

    # Dispatch
    if args.job in ["collector", "pipeline"]:
        run_all = args.batch_all or not args.municipality_id
        if run_all:
            if not targets_data:
                print("Error: collector/pipeline without --municipality_id requires a valid targets file")
                return

            collector_job = CollectorJob()
            for target in targets_data.get("targets", []):
                municipality_id = target.get("municipality_id")
                db = get_db()
                municipality_name = resolve_municipality_name(
                    municipality_id,
                    fallback_name=target.get("municipality_name") or municipality_id,
                    db=db,
                )
                search_municipality_ids = target.get("search_municipality_ids") or [municipality_id]
                search_engine_ids = resolve_engine_ids(targets_data, search_municipality_ids)
                domains = target.get("domains") or [args.domain]

                for domain in domains:
                    catalog_id = await create_catalog(
                        municipality_id, domain, municipality_name
                    )
                    await collector_job.run(
                        catalog_id,
                        municipality_id,
                        municipality_name,
                        domain,
                        search_engine_ids=search_engine_ids,
                    )
                    if args.job == "pipeline":
                        deduper_job = DeduperJob()
                        structurer_job = StructurerJob()
                        await deduper_job.run(catalog_id, municipality_id, domain)
                        await structurer_job.run(catalog_id, municipality_id, domain)
            return

        collector_job = CollectorJob()
        # Fetch name if missing (Mock or DB lookup)
        m_name = args.municipality_name
        search_engine_ids = None

        if targets_data:
            target = resolve_target(targets_data, args.municipality_id)
            if target:
                if not m_name:
                    m_name = target.get("municipality_name") or m_name
                search_municipality_ids = target.get("search_municipality_ids") or [args.municipality_id]
                search_engine_ids = resolve_engine_ids(targets_data, search_municipality_ids)
                if not search_engine_ids:
                    print(
                        f"Warning: no search engines resolved for municipality '{args.municipality_id}'"
                    )

        db = get_db()
        m_name = resolve_municipality_name(args.municipality_id, fallback_name=m_name, db=db)

        if not catalog_id:
            catalog_id = await create_catalog(args.municipality_id, args.domain, m_name)

        await collector_job.run(
            catalog_id,
            args.municipality_id,
            m_name,
            args.domain,
            search_engine_ids=search_engine_ids,
        )

        if args.job == "pipeline":
            deduper_job = DeduperJob()
            structurer_job = StructurerJob()
            await deduper_job.run(catalog_id, args.municipality_id, args.domain)
            await structurer_job.run(catalog_id, args.municipality_id, args.domain)
        
    elif args.job == "deduper":
        job = DeduperJob()
        await job.run(catalog_id, args.municipality_id, args.domain)
        
    elif args.job == "structurer":
        job = StructurerJob()
        await job.run(catalog_id, args.municipality_id, args.domain)

if __name__ == "__main__":
    asyncio.run(main())
