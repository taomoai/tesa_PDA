import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from fastapi import HTTPException
from ...schemas.bot import BotConfigSchema

logger = logging.getLogger(__name__)

# Configs directory path - relative to project root
CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"


class ConfigLoader:
    """
    Phase 1 implementation: Load bot configurations from JSON files
    Phase 2: This will be replaced with database queries
    """
    
    def __init__(self):
        self.configs_dir = CONFIGS_DIR
        logger.info(f"ConfigLoader initialized with configs directory: {self.configs_dir}")
    
    @lru_cache(maxsize=32)
    def load_config(self, bot_id: str) -> BotConfigSchema:
        """
        Load a bot configuration by bot_id from JSON file
        
        Args:
            bot_id: The unique identifier for the bot
            
        Returns:
            BotConfigSchema: Parsed and validated bot configuration
            
        Raises:
            HTTPException: If config file not found or invalid
        """
        config_path = self.configs_dir / f"{bot_id}.json"
        
        if not config_path.exists():
            logger.error(f"Config file not found: {config_path}")
            raise HTTPException(
                status_code=404,
                detail=f"Bot configuration for '{bot_id}' not found"
            )
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                return BotConfigSchema(**config_data)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {config_path}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Invalid configuration format for bot '{bot_id}'"
            )
        except Exception as e:
            logger.error(f"Error loading config for bot '{bot_id}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load configuration for bot '{bot_id}'"
            )
    
    def list_available_bots(self) -> List[str]:
        """
        List all available bot configurations
        
        Returns:
            List[str]: List of bot IDs
        """
        try:
            if not self.configs_dir.exists():
                logger.warning(f"Configs directory does not exist: {self.configs_dir}")
                return []
            
            bot_files = list(self.configs_dir.glob("*.json"))
            bot_ids = [f.stem for f in bot_files]
            logger.info(f"Found {len(bot_ids)} bot configurations: {bot_ids}")
            return bot_ids
        except Exception as e:
            logger.error(f"Error listing available bots: {e}")
            return []
    
    def reload_config(self, bot_id: str = None):
        """
        Clear cache for a specific bot or all bots
        
        Args:
            bot_id: Bot ID to reload, or None to reload all
        """
        if bot_id:
            # Clear specific bot from cache
            self.load_config.cache_clear()
            logger.info(f"Reloaded configuration for bot: {bot_id}")
        else:
            # Clear entire cache
            self.load_config.cache_clear()
            logger.info("Reloaded all bot configurations")


# Global instance
config_loader = ConfigLoader()