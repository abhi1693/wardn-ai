class MCPRegistryError(Exception):
    pass


class DuplicateMCPServerVersionError(MCPRegistryError):
    pass


class MCPServerNotFoundError(MCPRegistryError):
    pass


class MCPServerInstallationNotFoundError(MCPRegistryError):
    pass


class MCPServerInstallationFailedError(MCPRegistryError):
    pass


class MCPServerInstallationUnsupportedError(MCPRegistryError):
    pass


class MCPServerVersionInUseError(MCPRegistryError):
    pass


class InvalidRegistryCursorError(MCPRegistryError):
    pass


class MCPCatalogSourceNotFoundError(MCPRegistryError):
    pass


class DuplicateMCPCatalogSourceError(MCPRegistryError):
    pass
