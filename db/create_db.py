import os

from eo_lib.domain.base import Base
from eo_lib.infrastructure.database.postgres_client import PostgresClient
from sqlalchemy import text, Table, Column, Integer, ForeignKey, DateTime

# Try to load .env for local configuration
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Also import eo_lib entities
from eo_lib.domain.entities import (
    Organization,
    OrganizationalUnit,
    Person,
    PersonEmail,
    Role,
    Team,
    TeamMember,
)

from research_domain import (
    Campus,
    CampusController,
    KnowledgeArea,
    KnowledgeAreaController,
    Researcher,
    ResearcherController,
    ResearchGroup,
    ResearchGroupController,
    RoleController,
    University,
    UniversityController,
)
# Workaround: Import directly from controllers module since not exported in __init__
from research_domain.controllers.controllers import (
    AdvisorshipController,
    FellowshipController,
)

from research_domain.domain.entities import Advisorship, Fellowship # Import new entities
from src.tracking.entities import (  # noqa: F401
    AttributeAssertion,
    EntityChangeLog,
    EntityMatch,
    IngestionRun,
    SourceRecord,
)

# Extension: Add start_date to ResearchGroup for fundamental metadata
if not hasattr(ResearchGroup, "start_date"):
    ResearchGroup.start_date = Column(DateTime, nullable=True)

# Manually define missing junction table for Research Domain extension
# Only define if not already present in metadata
if "initiative_knowledge_areas" not in Base.metadata.tables:
    initiative_knowledge_areas = Table(
        "initiative_knowledge_areas",
        Base.metadata,
        Column("initiative_id", Integer, ForeignKey("initiatives.id"), primary_key=True),
        Column("area_id", Integer, ForeignKey("knowledge_areas.id"), primary_key=True),
    )


def setup_database():
    """Initializes the database by dropping and recreating all tables."""
    storage_type = os.getenv("STORAGE_TYPE", "memory").lower()
    if storage_type not in ["postgres", "db"]:
        print(f"Skipping database initialization (STORAGE_TYPE is '{storage_type}').")
        return

    print("Initializing Database Tables...")
    client = PostgresClient()

    # Force drop all tables via CASCADE to handle constraints
    try:
        if "sqlite" not in str(client._engine.url):
            with client._engine.connect() as conn:
                print("Performing forced cleanup (DROP SCHEMA public CASCADE)...")
                conn.execute(text("DROP SCHEMA public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
                conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
                conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
                conn.commit()
        else:
            print("SQLite detected, dropping all tables via metadata...")
            Base.metadata.drop_all(client._engine)

    except Exception as e:
        print(f"Note: Error during forced cleanup (ignored): {e}")

    print("Recreating all tables via Base.metadata...")
    # This will create tables for all models registered with Base (including Advisorship/Fellowship if imported)
    Base.metadata.create_all(client._engine)

    # ETL-owned tables (spec 020 identity tables, enrichment column) come from
    # the migrations, so a reset database has them from the start.
    from sqlalchemy.orm import Session

    from src.db.migrations import run_migrations

    with Session(client._engine) as session:
        run_migrations(session)
    print("Database tables initialized successfully.")


def run_demo():
    print("--- Starting Database Initialization ---")
    setup_database()

    try:
        # 1. Initialize Controllers
        uni_ctrl = UniversityController()
        campus_ctrl = CampusController()
        researcher_ctrl = ResearcherController()
        group_ctrl = ResearchGroupController()
        area_ctrl = KnowledgeAreaController()
        role_ctrl = RoleController()
        adv_ctrl = AdvisorshipController()
        fel_ctrl = FellowshipController()

        # 2. Create University and Campus
        ifes = uni_ctrl.create_university(
            name="Instituto Federal do Espirito Santo", short_name="IFES"
        )
        print(f"Created University: {ifes.name}")

    except Exception as e:
        print(f"Error during initialization: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    run_demo()
