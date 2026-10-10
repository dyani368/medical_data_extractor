import logging

from app.main import initialize_database
from app.services.ingestion_worker import run_worker

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    initialize_database()
    run_worker()
