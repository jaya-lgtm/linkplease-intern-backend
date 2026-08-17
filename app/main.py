import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import engine, Base, SessionLocal
from app.api import rules, webhook, stats
from app.workers.dm_worker import run_dm_worker, recover_sending_jobs, stop_event as dm_stop
from app.workers.reconciliation_worker import run_reconciliation_worker, stop_event as recon_stop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up LinkPlease backend application...")
    
    db = SessionLocal()
    try:
        recover_sending_jobs(db)
    except Exception as e:
        logger.error(f"Error recovering sending jobs on startup: {e}")
    finally:
        db.close()
        
    dm_task = asyncio.create_task(run_dm_worker())
    recon_task = asyncio.create_task(run_reconciliation_worker())
    
    yield
    
    logger.info("Shutting down background workers...")
    dm_stop.set()
    recon_stop.set()
    
    await asyncio.gather(dm_task, recon_task, return_exceptions=True)
    logger.info("Application shutdown complete.")

app = FastAPI(
    title="LinkPlease API",
    description="Automated Instagram comment keyword-to-DM flow processing system.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(rules.router)
app.include_router(webhook.router)
app.include_router(stats.router)

@app.get("/")
def read_root():
    return {"name": "LinkPlease API", "version": "1.0.0", "docs": "/docs"}
