# -*- coding: utf-8 -*-
"""Exception hierarchy for bankhub."""


class BankhubError(Exception):
    """Base class for all bankhub errors."""


class ConfigError(BankhubError):
    """Raised when a configuration value is missing or invalid."""


class PluginError(BankhubError):
    """Raised when a source/destination plugin cannot be found or built."""


class MissingDependencyError(PluginError):
    """Raised when an optional integration's dependency is not installed."""

    def __init__(self, plugin: str, package: str):
        self.plugin = plugin
        self.package = package
        super().__init__(
            f"The '{plugin}' integration requires the '{package}' package. "
            f"Install it with: pip install {package}"
        )


class SourceError(BankhubError):
    """Raised when a source fails to fetch or parse data."""


class DestinationError(BankhubError):
    """Raised when a destination fails to deliver transactions."""


class MappingError(BankhubError):
    """Raised when an account cannot be mapped to a destination account."""
