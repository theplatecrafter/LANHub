"""
LANHub System-Level Update Manager

Handles detection and execution of system-level updates from the updates/ directory.
This is separate from application updates (in updates table) — this handles infrastructure
changes like Docker image builds, system package installations, and configuration migrations.

Updates are tracked in a manifest file to prevent re-execution.

Usage:
    from functions.system_updates import check_for_updates, apply_pending_updates
    
    # Check if updates are available
    pending = check_for_updates()
    
    # Apply them
    results = apply_pending_updates()
"""

import os
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Get project root (parent of functions directory)
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
UPDATES_DIR = PROJECT_ROOT / "updates"
MANIFEST_FILE = PROJECT_ROOT / ".lanhub_updates_manifest"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure logs directory exists
LOGS_DIR.mkdir(exist_ok=True)


def _load_manifest() -> Dict:
    """Load the updates manifest file."""
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read manifest: {e}. Starting fresh.")
            return {"applied": {}, "last_check": None}
    return {"applied": {}, "last_check": None}


def _save_manifest(manifest: Dict):
    """Save the updates manifest file."""
    try:
        with open(MANIFEST_FILE, "w") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save manifest: {e}")
        raise


def _get_script_metadata(script_path: Path) -> Dict:
    """
    Parse metadata from an update script.
    
    Expected format in first 10 lines:
        # Update: Human readable name
        # Version: 1.1.0
        # Requires restart: yes/no
        # Requires sudo: yes/no
        # Requires input: yes/no
        # Description: What this update does
    """
    metadata = {
        "name": script_path.stem,
        "version": None,
        "requires_restart": False,
        "requires_sudo": False,
        "requires_input": False,
        "description": "",
    }
    
    try:
        with open(script_path, "r") as f:
            for i, line in enumerate(f):
                if i >= 10:  # Only check first 10 lines
                    break
                line = line.strip()
                
                if line.startswith("# Update:"):
                    metadata["name"] = line.replace("# Update:", "").strip()
                elif line.startswith("# Version:"):
                    metadata["version"] = line.replace("# Version:", "").strip()
                elif line.startswith("# Requires restart:"):
                    metadata["requires_restart"] = "yes" in line.lower()
                elif line.startswith("# Requires sudo:"):
                    metadata["requires_sudo"] = "yes" in line.lower()
                elif line.startswith("# Requires input:"):
                    metadata["requires_input"] = "yes" in line.lower()
                elif line.startswith("# Description:"):
                    metadata["description"] = line.replace("# Description:", "").strip()
    except Exception as e:
        logger.warning(f"Failed to parse metadata from {script_path}: {e}")
    
    return metadata


def _get_all_updates() -> Dict[str, List[Tuple[Path, Dict]]]:
    """
    Find all update scripts organized by version.
    
    Returns:
        Dict of version -> [(script_path, metadata), ...]
    """
    if not UPDATES_DIR.exists():
        return {}
    
    updates = {}
    
    # Find all version directories (v1.0.0, v1.1.0, etc.)
    for version_dir in sorted(UPDATES_DIR.iterdir()):
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        
        version = version_dir.name
        scripts = []
        
        # Find all .sh files in the version directory, sorted numerically
        for script_file in sorted(version_dir.glob("*.sh")):
            metadata = _get_script_metadata(script_file)
            scripts.append((script_file, metadata))
        
        if scripts:
            updates[version] = scripts
    
    return updates


def check_for_updates() -> Dict[str, List[Dict]]:
    """
    Check for pending updates.
    
    Returns:
        Dict mapping version -> list of pending update info dicts
    """
    all_updates = _get_all_updates()
    manifest = _load_manifest()
    applied = manifest.get("applied", {})
    
    pending = {}
    
    for version, scripts in all_updates.items():
        pending_in_version = []
        
        for script_path, metadata in scripts:
            script_name = script_path.stem
            
            # Check if already applied
            if version in applied and script_name in applied[version]:
                continue
            
            pending_in_version.append({
                "script": script_name,
                "name": metadata["name"],
                "description": metadata["description"],
                "requires_restart": metadata["requires_restart"],
                "requires_sudo": metadata["requires_sudo"],
                "requires_input": metadata["requires_input"],
            })
        
        if pending_in_version:
            pending[version] = pending_in_version
    
    # Update last_check timestamp
    manifest["last_check"] = datetime.utcnow().isoformat() + "Z"
    _save_manifest(manifest)
    
    return pending


def apply_pending_updates(allow_interactive: bool = False) -> Dict:
    """
    Apply all pending updates in order.
    
    Args:
        allow_interactive: If True, allow updates that require user input
    
    Returns:
        Dict with:
            - success: bool
            - applied: list of applied update identifiers (version/script)
            - failed: list of failed update identifiers
            - errors: dict of error messages
            - requires_restart: bool
    """
    all_updates = _get_all_updates()
    manifest = _load_manifest()
    applied_list = manifest.get("applied", {})
    
    results = {
        "success": True,
        "applied": [],
        "failed": [],
        "errors": {},
        "requires_restart": False,
    }
    
    # Process updates in version order
    for version in sorted(all_updates.keys()):
        scripts = all_updates[version]
        
        if version not in applied_list:
            applied_list[version] = []
        
        for script_path, metadata in scripts:
            script_name = script_path.stem
            
            # Skip if already applied
            if script_name in applied_list[version]:
                continue
            
            # Skip if requires input and not allowed
            if metadata["requires_input"] and not allow_interactive:
                logger.info(f"Skipping {script_name} (requires user input)")
                continue
            
            # Execute the script
            try:
                logger.info(f"Applying update: {metadata['name']} ({script_name})")
                
                cmd = [str(script_path)]
                if metadata["requires_sudo"]:
                    cmd = ["sudo"] + cmd
                
                # Set execution environment
                env = os.environ.copy()
                env["LANHUB_ROOT"] = str(PROJECT_ROOT)
                
                # Run subprocess with real-time output (not buffered)
                # This lets users see progress in app logs instead of waiting for it to finish
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    env=env,
                    bufsize=1,  # Line-buffered for real-time output
                )
                
                # Log output line by line as the process runs
                output_lines = result.stdout.split('\n') if result.stdout else []
                for line in output_lines:
                    if line.strip():
                        logger.info(f"  {line}")
                
                if result.returncode == 0:
                    # Success
                    applied_list[version].append(script_name)
                    results["applied"].append(f"{version}/{script_name}")
                    logger.info(f"✓ Applied: {script_name}")
                    
                    if metadata["requires_restart"]:
                        results["requires_restart"] = True
                    
                elif result.returncode == 2:
                    # Exit code 2 = already applied (idempotent check)
                    applied_list[version].append(script_name)
                    logger.info(f"~ Already applied: {script_name}")
                    
                else:
                    # Failure
                    error_msg = result.stdout or "Unknown error"
                    results["success"] = False
                    results["failed"].append(f"{version}/{script_name}")
                    results["errors"][f"{version}/{script_name}"] = error_msg
                    logger.error(f"✗ Failed: {script_name}: {error_msg}")
                    
                    # Stop on first failure
                    break
            
            except subprocess.TimeoutExpired:
                results["success"] = False
                results["failed"].append(f"{version}/{script_name}")
                results["errors"][f"{version}/{script_name}"] = "Update timed out (5 minutes)"
                logger.error(f"✗ Timeout: {script_name}")
                break
            
            except Exception as e:
                results["success"] = False
                results["failed"].append(f"{version}/{script_name}")
                results["errors"][f"{version}/{script_name}"] = str(e)
                logger.error(f"✗ Error executing {script_name}: {e}")
                break
        
        if not results["success"]:
            break
    
    # Save manifest
    manifest["applied"] = applied_list
    _save_manifest(manifest)
    
    return results


def get_update_status() -> Dict:
    """Get current update status for display in admin panel."""
    pending = check_for_updates()
    has_pending = bool(pending)
    
    manifest = _load_manifest()
    last_check = manifest.get("last_check")
    
    total_applied = sum(len(v) for v in manifest.get("applied", {}).values())
    total_pending = sum(len(v) for v in pending.values())
    
    return {
        "has_pending": has_pending,
        "pending_count": total_pending,
        "applied_count": total_applied,
        "last_check": last_check,
        "pending": pending,
    }
