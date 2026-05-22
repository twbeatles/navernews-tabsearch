
from core.db_mutations_support.maintenance_support.deletion import _NewsDeletionMaintenanceMixin
from core.db_mutations_support.maintenance_support.optimize import _NewsOptimizeMaintenanceMixin
from core.db_mutations_support.maintenance_support.read_state import _NewsReadMaintenanceMixin


class _NewsMaintenanceMixin(
    _NewsDeletionMaintenanceMixin,
    _NewsReadMaintenanceMixin,
    _NewsOptimizeMaintenanceMixin,
):
    """Composes DB maintenance and read-state mutation responsibilities."""


__all__ = ["_NewsMaintenanceMixin"]
