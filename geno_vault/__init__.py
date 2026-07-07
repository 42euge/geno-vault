"""geno-vault — persistence + sync conductor for the geno object-notation registry.

Git-versions ~/.geno/workspace.json (the registry shared by geno-tt and
geno-surf), orchestrates pull/push across surfaces, and watches for changes
(reusing geno-pear's mtime-poll mechanism)."""

__version__ = "0.3.0"

from .cli import main

__all__ = ["main", "__version__"]
