import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "compliance.db")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# SQLite requires check_same_thread=False for FastAPI concurrency
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import src.database.models as models  # noqa
    Base.metadata.create_all(bind=engine)

    # SQLite migration: add reviewer_role if missing in human_decisions
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE human_decisions ADD COLUMN reviewer_role VARCHAR(64) DEFAULT 'AP_REVIEWER'"))
            conn.commit()
        except Exception:
            pass


    # Seed default RBAC users if missing
    db = SessionLocal()
    try:
        user_count = db.query(models.UserRecord).count()
        if user_count == 0:
            default_users = [
                models.UserRecord(
                    username="surya.prakash",
                    full_name="Surya Prakash",
                    role="AP_REVIEWER",
                    title="Accounts Payable Specialist",
                    avatar_color="brand",
                ),
                models.UserRecord(
                    username="elena.rostova",
                    full_name="Elena Rostova",
                    role="FINANCE_VP",
                    title="VP of Finance & Corporate Controller",
                    avatar_color="emerald",
                ),
                models.UserRecord(
                    username="marcus.vance",
                    full_name="Marcus Vance",
                    role="AUDITOR_READONLY",
                    title="Senior Forensic Compliance Auditor",
                    avatar_color="cyan",
                ),
            ]
            db.add_all(default_users)
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"[WARN] Failed seeding default users: {e}")
    finally:
        db.close()

