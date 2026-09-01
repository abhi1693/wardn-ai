class LicensingError(Exception):
    """Base licensing error safe to report to an administrator."""


class InvalidLicenseLeaseError(LicensingError):
    pass


class LicenseRenewalError(LicensingError):
    pass
