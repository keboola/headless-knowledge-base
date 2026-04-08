"""One-off script to backfill entity_type property from Neo4j labels.

For entities that have labels like :Entity:Technology but no entity_type property,
this sets entity_type = "Technology" (the non-Entity label).

Safe to run multiple times (only updates entities where entity_type IS NULL).
"""

import asyncio
import os
import sys

from neo4j import AsyncGraphDatabase


async def backfill(uri: str, user: str, password: str, dry_run: bool = True) -> None:
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    try:
        # Preview what would be updated
        async with driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity) WHERE e.entity_type IS NULL "
                "WITH e, head([l IN labels(e) WHERE l <> 'Entity']) AS etype "
                "WHERE etype IS NOT NULL "
                "RETURN etype, count(e) AS cnt ORDER BY cnt DESC"
            )
            counts = [(r["etype"], r["cnt"]) async for r in result]

        total = sum(c for _, c in counts)
        print(f"Found {total} entities missing entity_type property:")
        for etype, cnt in counts:
            print(f"  {etype}: {cnt}")

        if dry_run:
            print("\n[DRY RUN] No changes applied. Run with --apply to backfill.")
            return

        # Apply backfill
        async with driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity) WHERE e.entity_type IS NULL "
                "WITH e, head([l IN labels(e) WHERE l <> 'Entity']) AS etype "
                "WHERE etype IS NOT NULL "
                "SET e.entity_type = etype "
                "RETURN count(e) AS updated"
            )
            record = await result.single()
            print(f"\nBackfilled {record['updated']} entities with entity_type property.")

        # Verify
        async with driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity) WHERE e.entity_type IS NOT NULL "
                "RETURN e.entity_type AS etype, count(e) AS cnt ORDER BY cnt DESC"
            )
            counts = [(r["etype"], r["cnt"]) async for r in result]

        total = sum(c for _, c in counts)
        print(f"\nVerification: {total} entities now have entity_type property:")
        for etype, cnt in counts:
            print(f"  {etype}: {cnt}")

    finally:
        await driver.close()


if __name__ == "__main__":
    uri = os.environ.get("NEO4J_URI", "bolt+s://neo4j.internal.keboola.com:443")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]

    dry_run = "--apply" not in sys.argv
    print(f"Target: {uri}")
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}\n")

    asyncio.run(backfill(uri, user, password, dry_run))
