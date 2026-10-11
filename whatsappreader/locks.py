"""Exclusive, cross-process file locks for orchestrator and Chromium profile."""
import fcntl
from contextlib import contextmanager
from .settings import data_path

class AlreadyRunning(Exception):pass

@contextmanager
def exclusive_lock(name='orchestrator.lock'):
    path=data_path(name);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as fp:
        try:fcntl.flock(fp,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise AlreadyRunning('Another process already holds the '+name+' lock.')
        try:yield
        finally:fcntl.flock(fp,fcntl.LOCK_UN)
