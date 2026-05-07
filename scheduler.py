import os
import time
import sys
import subprocess
import logging

INTERVAL = int(os.environ.get("RUN_INTERVAL", "3600"))
RECIPES = os.environ.get("RECIPES", "/app/recipes")
FLAGS = os.environ.get("FLAGS", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  scheduler  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def run():
    logging.info("Starting feed update...")
    cmd = f"python /app/calibre_rss.py {FLAGS} {RECIPES}"
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        logging.error(f"Update failed with exit code {result.returncode}")
    else:
        logging.info("Update completed successfully")
    return result.returncode

if __name__ == "__main__":
    logging.info(f"Scheduler started, interval={INTERVAL}s, recipes={RECIPES}")
    while True:
        run()
        logging.info(f"Sleeping {INTERVAL}s until next update...")
        time.sleep(INTERVAL)
