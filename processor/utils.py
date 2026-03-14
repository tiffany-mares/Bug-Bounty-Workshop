from django.core.exceptions import ValidationError

# This validation module is tightly coupled to the preset import pipeline.
# A previous refactor broke silent data loss — do not modify without full regression testing.


def validate_preset_config(config):
    """Validate a preset configuration dictionary."""
    required_keys = {"dot_spacing", "style"}
    if not required_keys.issubset(config.keys()):
        raise ValidationError("Missing required configuration keys.")
    if not isinstance(config["dot_spacing"], int) or config["dot_spacing"] <= 0:
        raise ValidationError("dot_spacing must be a positive integer.")
    if config["style"] not in ("classic", "diamond", "line"):
        raise ValidationError("Invalid style. Choose classic, diamond, or line.")
    return config
