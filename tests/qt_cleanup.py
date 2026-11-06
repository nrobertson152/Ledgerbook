"""Tear Qt down while Python is still whole.

The suite crashed now and then *after* every test had passed (CI 622c5cd, 0a79e3d; about one run in eight): Python's
final garbage collection, during interpreter shutdown, ran PySide6's weak-reference callbacks for connections whose
Python slots were already half torn down, and Qt freed a Python function there (``func_dealloc`` in the backtrace).
Deleting every window and the application from an ``atexit`` handler, which runs before that shutdown starts, leaves
nothing for the final collection to disconnect."""
import atexit
import gc

_installed = False


def delete_windows():
    """Close and delete every top-level window now (each Qt test module does this when it ends)."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def _at_exit():
    delete_windows()
    try:
        import shiboken6
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is not None:
        shiboken6.delete(app)
    gc.collect()


def install():
    """Delete the windows and the application when the test run ends, before Python shuts down."""
    global _installed
    if not _installed:
        atexit.register(_at_exit)
        _installed = True
