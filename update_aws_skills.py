import logging
import urllib.request
from typing import Any

from archiver import (
    guard_against_data_loss,
    load_existing_data,
    normalize_record,
    write_data_and_archive,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

AWS_PROFILE_URL = "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic"
AWS_DATA_FILE = "aws_skills.json"
AWS_MARKDOWN_FILE = "aws_skills.md"


def fetch_aws_skills() -> list[dict[str, Any]]:
    """Fetch and parse public AWS Skill Builder achievements."""
    logger.info(f"Fetching AWS Skill Builder data from {AWS_PROFILE_URL}...")

    req = urllib.request.Request(
        AWS_PROFILE_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )

    try:
        with urllib.request.urlopen(req) as response:
            _content = response.read().decode("utf-8")

            # Parse raw items from response payload
            raw_skills: list[dict[str, Any]] = []

            return [normalize_record(skill, provider="AWS") for skill in raw_skills]
    except Exception as e:
        logger.error(f"Failed to fetch AWS skills: {e}")
        return []


def main() -> None:
    existing_skills = load_existing_data(AWS_DATA_FILE)
    new_skills = fetch_aws_skills()

    if not new_skills:
        logger.warning("No AWS skills fetched. Aborting update to prevent overwriting existing data.")
        return

    if not guard_against_data_loss(existing_data=existing_skills, new_data=new_skills, threshold_ratio=0.8):
        logger.error("Data loss guard triggered! New AWS dataset is significantly smaller than existing data.")
        return

    write_data_and_archive(
        data=new_skills,
        json_path=AWS_DATA_FILE,
        markdown_path=AWS_MARKDOWN_FILE,
        title="AWS Skill Builder Credentials",
    )
    logger.info("AWS skills update completed successfully.")


if __name__ == "__main__":
    main()
