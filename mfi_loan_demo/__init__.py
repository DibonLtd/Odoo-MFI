from . import models


def uninstall_hook(env):
    """Remove every sample record before the module's own data goes."""
    env["mfi.demo"]._unload()
