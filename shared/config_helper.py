"""
shared/config_helper.py

Helper utilities for accessing game configuration parameters.
Standardizes config access pattern across all games.
"""

from typing import Any, Dict


def get_game_config(
    config_module,
    prefix: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Retrieve game configuration parameters from config module.
    
    Eliminates verbose _cfg() functions scattered across game modules.
    
    Args:
        config_module: The config module to read from
        prefix: Configuration prefix (e.g., 'SLITHER', 'SCRIBBLE')
        params: Dict mapping param names to default values
                e.g., {'TICK_HZ': 20, 'BASE_SPEED': 3.5}
    
    Returns:
        Dict of {param_name: value} with defaults applied
    
    Example:
        cfg = get_game_config(config, 'SLITHER', {
            'TICK_HZ': 20,
            'BASE_SPEED': 3.5,
            'MAX_SEGS': 700,
        })
        # Returns: {'TICK_HZ': 20, 'BASE_SPEED': 3.5, ...}
    """
    result = {}
    for param_name, default_value in params.items():
        config_key = f"{prefix}_{param_name}"
        value = getattr(config_module, config_key, default_value)
        result[param_name] = value
    return result


def get_game_config_typed(
    config_module,
    prefix: str,
    params: Dict[str, tuple[type, Any]],
) -> Dict[str, Any]:
    """
    Retrieve game configuration parameters with type conversion.
    
    Args:
        config_module: The config module to read from
        prefix: Configuration prefix (e.g., 'SLITHER', 'SCRIBBLE')
        params: Dict mapping param names to (type, default_value) tuples
                e.g., {'TICK_HZ': (int, 20), 'BASE_SPEED': (float, 3.5)}
    
    Returns:
        Dict of {param_name: typed_value} with defaults applied
    
    Example:
        cfg = get_game_config_typed(config, 'SLITHER', {
            'TICK_HZ': (int, 20),
            'BASE_SPEED': (float, 3.5),
            'MAX_SEGS': (int, 700),
        })
    """
    result = {}
    for param_name, (type_conv, default_value) in params.items():
        config_key = f"{prefix}_{param_name}"
        value = getattr(config_module, config_key, default_value)
        try:
            result[param_name] = type_conv(value)
        except (TypeError, ValueError):
            result[param_name] = default_value
    return result
