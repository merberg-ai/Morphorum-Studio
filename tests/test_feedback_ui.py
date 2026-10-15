"""S5.4: feedback banner behavior under offscreen Qt."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from morphorum_studio.ui.feedback import FeedbackBanner


def test_feedback_busy_success_and_error():
    app = QApplication.instance() or QApplication(["studio-feedback"])
    banner = FeedbackBanner()
    banner.notify("Contacting backend", busy=True)
    assert banner.isVisible() and banner.progress.isVisible()
    assert not banner._timer.isActive()
    banner.notify("Saved", kind="success")
    assert banner.message.text() == "Saved" and not banner.progress.isVisible()
    assert banner._timer.isActive()
    banner.notify("Connection failed", kind="error")
    assert banner.message.text() == "Connection failed"
    assert not banner._timer.isActive()
    banner.dismiss.click()
    assert not banner.isVisible()
    banner.deleteLater()
    app.processEvents()
