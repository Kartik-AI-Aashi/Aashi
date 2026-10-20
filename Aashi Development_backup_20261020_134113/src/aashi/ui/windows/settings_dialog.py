"""User-facing controls for desktop-assistant privacy and behavior."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aashi.automation import MemoryStore, MemoryValidationError
from aashi.config.assistant_settings import AssistantSettingsError, AutomationSettings

__all__ = ["AssistantSettingsDialog"]


class AssistantSettingsDialog(QDialog):
    """Edit persisted assistant settings and explicitly approved memories."""

    settings_saved = Signal(object)

    def __init__(
        self,
        settings: AutomationSettings,
        memory: MemoryStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aashi settings")
        self.setMinimumWidth(560)
        self._settings = settings
        self._memory = memory

        tabs = QTabWidget(self)
        tabs.addTab(self._build_assistant_tab(), "Assistant")
        tabs.addTab(self._build_privacy_tab(), "Privacy")
        tabs.addTab(self._build_memory_tab(), "Memory")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _build_assistant_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)

        self._proactive = QCheckBox("Allow proactive conversations", widget)
        self._proactive.setChecked(self._settings.proactive_enabled)
        self._proactive_speech = QCheckBox("Allow proactive speech", widget)
        self._proactive_speech.setChecked(self._settings.proactive_speech)
        self._microphone = QCheckBox("Allow microphone access", widget)
        self._microphone.setChecked(self._settings.microphone_enabled)
        self._monitoring = QCheckBox("Enable screen monitoring", widget)
        self._monitoring.setChecked(self._settings.screen_monitoring_enabled)
        self._external_analysis = QCheckBox(
            "Allow screen images to be sent to the configured vision provider",
            widget,
        )
        self._external_analysis.setChecked(self._settings.allow_external_screen_analysis)
        self._dnd = QCheckBox("Do not disturb", widget)
        self._dnd.setChecked(self._settings.do_not_disturb)
        self._memory_enabled = QCheckBox("Allow approved long-term memory", widget)
        self._memory_enabled.setChecked(self._settings.memory_enabled)
        self._interruptible = QCheckBox("Allow speech interruption", widget)
        self._interruptible.setChecked(self._settings.interruptible_speech)

        for control in (
            self._proactive,
            self._proactive_speech,
            self._microphone,
            self._monitoring,
            self._external_analysis,
            self._dnd,
            self._memory_enabled,
            self._interruptible,
        ):
            form.addRow(control)

        self._interval = QSpinBox(widget)
        self._interval.setRange(5, 3600)
        self._interval.setSuffix(" seconds")
        self._interval.setValue(self._settings.monitor_interval_seconds)
        form.addRow("Monitoring frequency", self._interval)

        self._language = QLineEdit(self._settings.speech_language, widget)
        self._language.setPlaceholderText("en-IN or hi-IN")
        form.addRow("Voice language", self._language)

        self._quiet_start = QLineEdit(self._settings.quiet_hours_start, widget)
        self._quiet_end = QLineEdit(self._settings.quiet_hours_end, widget)
        form.addRow("Quiet hours start", self._quiet_start)
        form.addRow("Quiet hours end", self._quiet_end)
        return widget

    def _build_privacy_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)
        self._roots = QLineEdit(";".join(self._settings.authorized_roots), widget)
        self._roots.setPlaceholderText(r"C:\Projects;C:\Users\You\Documents")
        form.addRow("Authorized folders", self._roots)
        self._excluded = QLineEdit(";".join(self._settings.excluded_applications), widget)
        self._excluded.setPlaceholderText("banking;password manager;private")
        form.addRow("Excluded applications", self._excluded)

        note = QLabel(
            "Aashi captures screens only while monitoring is enabled. External "
            "vision analysis is separately controlled above. Passwords, banking "
            "and private applications should remain excluded.",
            widget,
        )
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(note)
        return widget

    def _build_memory_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Only facts explicitly approved by you are stored."))
        self._memory_list = QListWidget(widget)
        self._refresh_memory()
        layout.addWidget(self._memory_list)
        row = QHBoxLayout()
        delete = QPushButton("Delete selected memory", widget)
        delete.clicked.connect(self._delete_selected_memory)
        clear = QPushButton("Clear all memory", widget)
        clear.clicked.connect(self._clear_memory)
        row.addWidget(delete)
        row.addWidget(clear)
        layout.addLayout(row)
        return widget

    def _refresh_memory(self) -> None:
        self._memory_list.clear()
        try:
            facts = self._memory.list()
        except MemoryValidationError as exc:
            self._memory_list.addItem(f"Memory file needs attention: {exc}")
            return
        for fact in facts:
            self._memory_list.addItem(f"{fact.key}: {fact.value}")

    def _delete_selected_memory(self) -> None:
        item = self._memory_list.currentItem()
        if item is None:
            return
        key = item.text().split(":", 1)[0]
        answer = QMessageBox.question(
            self,
            "Delete memory?",
            f"Delete the approved memory '{key}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._memory.delete(key, approved=True)
            self._refresh_memory()

    def _clear_memory(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear memory?",
            "Delete every approved memory fact?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._memory.clear(approved=True)
            self._refresh_memory()

    def _save(self) -> None:
        roots = tuple(item.strip() for item in self._roots.text().split(";") if item.strip())
        excluded = tuple(item.strip() for item in self._excluded.text().split(";") if item.strip())
        candidate = AutomationSettings(
            proactive_enabled=self._proactive.isChecked(),
            proactive_speech=self._proactive_speech.isChecked(),
            microphone_enabled=self._microphone.isChecked(),
            screen_monitoring_enabled=self._monitoring.isChecked(),
            monitor_interval_seconds=self._interval.value(),
            excluded_applications=excluded,
            quiet_hours_start=self._quiet_start.text().strip(),
            quiet_hours_end=self._quiet_end.text().strip(),
            do_not_disturb=self._dnd.isChecked(),
            authorized_roots=roots,
            memory_enabled=self._memory_enabled.isChecked(),
            speech_language=self._language.text().strip(),
            interruptible_speech=self._interruptible.isChecked(),
            allow_external_screen_analysis=self._external_analysis.isChecked(),
            recommendation_threshold=self._settings.recommendation_threshold,
            warning_threshold=self._settings.warning_threshold,
            proactive_cooldown_seconds=self._settings.proactive_cooldown_seconds,
            duplicate_window_seconds=self._settings.duplicate_window_seconds,
        )
        try:
            normalized = candidate.validate()
        except (AssistantSettingsError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return
        self._settings = normalized
        self.settings_saved.emit(normalized)
        self.accept()
