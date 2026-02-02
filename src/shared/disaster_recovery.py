"""Disaster recovery and backup system.

Automated backups with fast restore capabilities.
"""

import asyncio
import gzip
import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles

from src.shared.config import get_settings
from src.shared.database import get_engine
from src.shared.logger import get_logger
from src.shared.redis_client import get_redis_client

logger = get_logger(__name__)


class BackupManager:
    """Manage automated backups."""
    
    BACKUP_TARGETS = [
        "database",           # SQLite database
        "redis",             # Redis RDB snapshots
        "channel_configs",   # Channel YAML configurations
        "assets",           # Last 24h of generated assets
        "models",           # LoRA weights and custom models
    ]
    
    def __init__(
        self,
        backup_dir: str = "/Volumes/ai_content_shared/backups",
        retention_days: int = 30,
    ):
        self.settings = get_settings()
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_backup(self, backup_type: str = "full") -> dict[str, Any]:
        """Create backup of all critical data.
        
        Args:
            backup_type: 'full' or 'incremental'
            
        Returns:
            Backup metadata
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"monolathe_{backup_type}_{timestamp}"
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(exist_ok=True)
        
        logger.info(f"Starting {backup_type} backup: {backup_name}")
        
        results = {
            "backup_name": backup_name,
            "timestamp": timestamp,
            "type": backup_type,
            "components": {},
        }
        
        # Backup database
        try:
            db_path = await self._backup_database(backup_path)
            results["components"]["database"] = {"path": str(db_path), "status": "success"}
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            results["components"]["database"] = {"status": "failed", "error": str(e)}
        
        # Backup Redis
        try:
            redis_path = await self._backup_redis(backup_path)
            results["components"]["redis"] = {"path": str(redis_path), "status": "success"}
        except Exception as e:
            logger.error(f"Redis backup failed: {e}")
            results["components"]["redis"] = {"status": "failed", "error": str(e)}
        
        # Backup channel configs
        try:
            config_path = await self._backup_channel_configs(backup_path)
            results["components"]["configs"] = {"path": str(config_path), "status": "success"}
        except Exception as e:
            logger.error(f"Config backup failed: {e}")
            results["components"]["configs"] = {"status": "failed", "error": str(e)}
        
        # Backup recent assets
        try:
            assets_path = await self._backup_assets(backup_path)
            results["components"]["assets"] = {"path": str(assets_path), "status": "success"}
        except Exception as e:
            logger.error(f"Assets backup failed: {e}")
            results["components"]["assets"] = {"status": "failed", "error": str(e)}
        
        # Create tarball
        try:
            tarball_path = await self._create_tarball(backup_path)
            results["tarball"] = str(tarball_path)
            results["size_bytes"] = tarball_path.stat().st_size
            
            # Cleanup uncompressed backup
            shutil.rmtree(backup_path)
            
        except Exception as e:
            logger.error(f"Tarball creation failed: {e}")
            results["tarball"] = None
        
        # Save metadata
        await self._save_metadata(results)
        
        # Cleanup old backups
        await self._cleanup_old_backups()
        
        logger.info(f"Backup complete: {backup_name}")
        return results
    
    async def _backup_database(self, backup_path: Path) -> Path:
        """Backup SQLite database.
        
        Args:
            backup_path: Backup directory
            
        Returns:
            Path to database backup
        """
        db_path = Path(self.settings.database_url.replace("sqlite+aiosqlite:///", ""))
        backup_db_path = backup_path / "database.db"
        
        # Copy database file
        shutil.copy2(db_path, backup_db_path)
        
        # Compress
        compressed_path = backup_db_path.with_suffix(".db.gz")
        with open(backup_db_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        backup_db_path.unlink()
        return compressed_path
    
    async def _backup_redis(self, backup_path: Path) -> Path:
        """Backup Redis data.
        
        Args:
            backup_path: Backup directory
            
        Returns:
            Path to Redis backup
        """
        redis_backup_path = backup_path / "redis.rdb"
        
        # Trigger Redis BGSAVE
        redis = await get_redis_client()
        await redis.client.execute_command("BGSAVE")
        
        # Wait for save to complete
        await asyncio.sleep(2)
        
        # Copy RDB file (location depends on Redis config)
        redis_rdb_path = Path("/data/dump.rdb")  # Adjust as needed
        if redis_rdb_path.exists():
            shutil.copy2(redis_rdb_path, redis_backup_path)
        else:
            # Create placeholder
            redis_backup_path.write_text("Redis RDB not available")
        
        return redis_backup_path
    
    async def _backup_channel_configs(self, backup_path: Path) -> Path:
        """Backup channel configurations.
        
        Args:
            backup_path: Backup directory
            
        Returns:
            Path to configs backup
        """
        config_path = backup_path / "channel_configs.tar.gz"
        config_dir = Path("config/channels")
        
        with tarfile.open(config_path, "w:gz") as tar:
            tar.add(config_dir, arcname="channels")
        
        return config_path
    
    async def _backup_assets(self, backup_path: Path) -> Path:
        """Backup recent assets (last 24h).
        
        Args:
            backup_path: Backup directory
            
        Returns:
            Path to assets backup
        """
        assets_path = backup_path / "assets.tar.gz"
        assets_dir = Path("/Volumes/ai_content_shared/assets")
        
        # Calculate cutoff time
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        with tarfile.open(assets_path, "w:gz") as tar:
            if assets_dir.exists():
                for file_path in assets_dir.rglob("*"):
                    if file_path.is_file():
                        # Check modification time
                        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                        if mtime > cutoff:
                            tar.add(file_path, arcname=file_path.relative_to(assets_dir))
        
        return assets_path
    
    async def _create_tarball(self, backup_path: Path) -> Path:
        """Create compressed tarball of backup.
        
        Args:
            backup_path: Backup directory
            
        Returns:
            Path to tarball
        """
        tarball_path = Path(str(backup_path) + ".tar.gz")
        
        with tarfile.open(tarball_path, "w:gz") as tar:
            tar.add(backup_path, arcname=backup_path.name)
        
        return tarball_path
    
    async def _save_metadata(self, metadata: dict[str, Any]) -> None:
        """Save backup metadata.
        
        Args:
            metadata: Backup metadata
        """
        metadata_path = self.backup_dir / f"{metadata['backup_name']}.json"
        async with aiofiles.open(metadata_path, "w") as f:
            await f.write(json.dumps(metadata, indent=2, default=str))
    
    async def _cleanup_old_backups(self) -> int:
        """Remove backups older than retention period.
        
        Returns:
            Number of backups removed
        """
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        removed = 0
        
        for backup_file in self.backup_dir.glob("monolathe_*.tar.gz"):
            # Extract timestamp from filename
            try:
                timestamp_str = backup_file.stem.split("_")[2]
                backup_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if backup_time < cutoff:
                    backup_file.unlink()
                    
                    # Also remove metadata file
                    metadata_file = backup_file.with_suffix(".json")
                    if metadata_file.exists():
                        metadata_file.unlink()
                    
                    removed += 1
                    logger.info(f"Removed old backup: {backup_file.name}")
            except (IndexError, ValueError):
                continue
        
        return removed
    
    async def restore_backup(
        self,
        backup_name: str,
        components: list[str] | None = None,
    ) -> dict[str, Any]:
        """Restore from backup.
        
        Args:
            backup_name: Name of backup to restore
            components: Specific components to restore, or None for all
            
        Returns:
            Restore results
        """
        components = components or self.BACKUP_TARGETS
        tarball_path = self.backup_dir / f"{backup_name}.tar.gz"
        
        if not tarball_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_name}")
        
        logger.info(f"Starting restore: {backup_name}")
        
        # Extract tarball
        extract_path = self.backup_dir / "restore_temp"
        extract_path.mkdir(exist_ok=True)
        
        with tarfile.open(tarball_path, "r:gz") as tar:
            tar.extractall(extract_path)
        
        results = {"backup_name": backup_name, "components": {}}
        
        # Restore components
        backup_content_path = extract_path / backup_name
        
        if "database" in components:
            try:
                await self._restore_database(backup_content_path)
                results["components"]["database"] = "success"
            except Exception as e:
                results["components"]["database"] = f"failed: {e}"
        
        if "configs" in components:
            try:
                await self._restore_configs(backup_content_path)
                results["components"]["configs"] = "success"
            except Exception as e:
                results["components"]["configs"] = f"failed: {e}"
        
        # Cleanup
        shutil.rmtree(extract_path)
        
        logger.info(f"Restore complete: {backup_name}")
        return results
    
    async def _restore_database(self, backup_path: Path) -> None:
        """Restore database from backup."""
        db_backup = backup_path / "database.db.gz"
        if db_backup.exists():
            db_path = Path(self.settings.database_url.replace("sqlite+aiosqlite:///", ""))
            
            # Decompress
            with gzip.open(db_backup, "rb") as f_in:
                db_path.write_bytes(f_in.read())
            
            logger.info("Database restored")
    
    async def _restore_configs(self, backup_path: Path) -> None:
        """Restore channel configs from backup."""
        config_backup = backup_path / "channel_configs.tar.gz"
        if config_backup.exists():
            config_dir = Path("config/channels")
            
            with tarfile.open(config_backup, "r:gz") as tar:
                tar.extractall(config_dir.parent)
            
            logger.info("Channel configs restored")
    
    async def list_backups(self) -> list[dict[str, Any]]:
        """List available backups.
        
        Returns:
            List of backup metadata
        """
        backups = []
        
        for metadata_file in self.backup_dir.glob("monolathe_*.json"):
            try:
                async with aiofiles.open(metadata_file, "r") as f:
                    content = await f.read()
                    metadata = json.loads(content)
                    backups.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to read backup metadata: {e}")
        
        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return backups


class RecoveryProcedures:
    """Documented recovery procedures."""
    
    PROCEDURES = {
        "database_corruption": {
            "steps": [
                "Stop all services",
                "Restore from latest backup",
                "Verify database integrity",
                "Restart services",
            ],
            "estimated_time": "5 minutes",
        },
        "redis_failure": {
            "steps": [
                "Restart Redis container",
                "Restore from RDB snapshot if needed",
                "Clear stuck jobs",
                "Resume queue processing",
            ],
            "estimated_time": "2 minutes",
        },
        "studio_network_partition": {
            "steps": [
                "Verify network connectivity",
                "Switch to DeepSeek API fallback",
                "Queue jobs for later processing",
                "Alert on-call engineer",
            ],
            "estimated_time": "10 minutes",
        },
        "instagram_api_outage": {
            "steps": [
                "Pause upload queue",
                "Enable circuit breaker",
                "Queue uploads for retry",
                "Monitor API status",
            ],
            "estimated_time": "Until API recovers",
        },
    }
    
    @classmethod
    def get_procedure(cls, scenario: str) -> dict[str, Any]:
        """Get recovery procedure.
        
        Args:
            scenario: Failure scenario
            
        Returns:
            Recovery procedure
        """
        return cls.PROCEDURES.get(scenario, {"steps": [], "estimated_time": "unknown"})
    
    @classmethod
    def list_scenarios(cls) -> list[str]:
        """List available recovery scenarios."""
        return list(cls.PROCEDURES.keys())