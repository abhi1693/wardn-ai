class ScheduledTaskError(Exception):
    pass


class ScheduledTaskNotFoundError(ScheduledTaskError):
    pass


class DuplicateScheduledTaskError(ScheduledTaskError):
    pass


class InvalidScheduledTaskError(ScheduledTaskError):
    pass
