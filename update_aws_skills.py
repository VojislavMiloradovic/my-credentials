import json
import logging
import urllib.request
from typing import Dict, Any, List

# Import shared pipeline utilities from archiver.py
from archiver import (
    load_existing_data,
    guard_against_data_loss,
    normalize_record,
    write_data_and_archive,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

AWS_PROFILE_URL = "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic"
AWS_DATA_FILE = "aws_skills.json"
AWS_MARKDOWN_FILE = "aws_skills.md"

def fetch_aws_skills() -> List[Dict[str, Any]]:
    """
    Fetch and parse public AWS Skill Builder achievements.
    """
    logging.info(f"Fetching AWS Skill Builder data from {AWS_PROFILE_URL}...")
    
    req = urllib.request.Request(
        AWS_PROFILE_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            html_or_json = response.read().decode("utf-8")
            
            # Parse raw items into structured dicts
            raw_skills = []  # Extracted items from profile payload
            
            # Pass each record through archiver's normalization utility
            normalized_skills = [
                normalize_record(skill, provider="AWS") 
                for skill in raw_skills
            ]
            return normalized_skills
    except Exception as e:
        logging.error(f"Failed to fetch AWS skills: {e}")
        return []

def main():
    # 1. Load previously saved state
    existing_skills = load_existing_data(AWS_DATA_FILE)

    # 2. Fetch latest skills profile
    new_skills = fetch_aws_skills()

    if not new_skills:
        logging.warning("No AWS skills fetched. Aborting update to prevent overwriting existing data.")
        return

    # 3. Guard against accidental data loss using archiver safety checks
    if not guard_against_data_loss(existing_data=existing_skills, new_data=new_skills, threshold_ratio=0.8):
        logging.error("Data loss guard triggered! New AWS dataset is significantly smaller than existing data.")
        return

    # 4. Delegate state saving, Markdown generation, and archive creation to archiver
    write_data_and_archive(
        data=new_skills,
        json_path=AWS_DATA_FILE,
        markdown_path=AWS_MARKDOWN_FILE,
        title="AWS Skill Builder Credentials"
    )
    logging.info("AWS skills update completed successfully.")

if __name__ == "__main__":
    main()
