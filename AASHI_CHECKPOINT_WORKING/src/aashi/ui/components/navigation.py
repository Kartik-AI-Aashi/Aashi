"""Navigation sidebar component.

A ChatGPT-style rail: a **New chat** button, a **Projects** section (create a
project, switch between them) and the **Chats** that belong to the selected
project. Every chat and project row has a hover "⋯" button that opens a menu:

* chat — Rename, Move to project ▸, Delete
* project — Rename, Delete

The sidebar owns only the interaction: it asks the user (dialogs, menus) and
reports the outcome through signals; the chat window performs the change.
Composed from design tokens and the active theme only — no literal colours.
"""

from __future__ import annotations

from dataclasses import replace as _replace

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qcolor, to_qfont
from aashi.ui.tokens.controls import ControlHeight
from aashi.ui.tokens.spacing import LAYOUT, Space
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = [
    "ConversationListItem",
    "DeleteConfirmationDialog",
    "NavigationSidebar",
    "ProjectListItem",
    "PromptDialog",
    "SidebarMode",
]

_ROW_HEIGHT_PX = 40
_PROJECT_ROW_HEIGHT_PX = 36
_PROJECT_ROWS_VISIBLE = 4
_MAX_NAME_CHARS = 60


class SidebarMode:
    """Sidebar display modes."""

    HIDDEN = 0
    COMPACT = 1  # Icon-only
    EXPANDED = 2  # Full labels


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


class _ThemedDialog(QDialog):
    """Frameless, rounded, theme-aware dialog shell with a button row."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        window_title: str,
        heading: str,
        primary_text: str,
        *,
        destructive: bool,
        size: tuple[int, int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._destructive = destructive
        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setFixedSize(*size)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._container = QWidget()
        self._container.setObjectName("dialogContainer")
        self._container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._container)

        self._body = QVBoxLayout(self._container)
        self._body.setContentsMargins(Space.SPACE_300, Space.SPACE_300, Space.SPACE_300, Space.SPACE_300)
        self._body.setSpacing(Space.SPACE_200)

        self._heading = QLabel(heading)
        self._heading.setFont(to_qfont(style_for(TextRole.SECTION)))
        self._body.addWidget(self._heading)

        # Subclasses add their content between the heading and the buttons.
        self._content_index = self._body.count()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setFixedHeight(ControlHeight.DEFAULT.value)
        self._cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_button.clicked.connect(self.reject)
        self._primary_button = QPushButton(primary_text)
        self._primary_button.setFixedHeight(ControlHeight.DEFAULT.value)
        self._primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary_button.setDefault(True)
        self._primary_button.clicked.connect(self.accept)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._primary_button)
        self._body.addLayout(buttons)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    def _add_content(self, widget: QWidget) -> None:
        self._body.insertWidget(self._content_index, widget)
        self._content_index += 1

    def _restyle(self, *_: object) -> None:
        variables = qss_variables(self._theme_manager.theme)
        # Text on the filled button is the theme's "inverse" colour so it can
        # never vanish into the fill (danger-on-danger was invisible).
        fill = variables["color.danger"] if self._destructive else variables["color.accent"]
        ink = variables["color.text.inverse"] if self._destructive else variables["color.accent.on"]
        self._container.setStyleSheet(f"""
            QWidget#dialogContainer {{
                background-color: {variables['color.surface']};
                border: {variables['border.hairline']} solid {variables['color.border.strong']};
                border-radius: {variables['radius.large']};
            }}
            QLabel {{ color: {variables['color.text']}; background: transparent; }}
            QLineEdit {{
                background-color: {variables['color.surface.nested']};
                color: {variables['color.text']};
                border: {variables['border.hairline']} solid {variables['color.border']};
                border-radius: {variables['radius.medium']};
                padding: 0 {Space.SPACE_150}px;
                min-height: {ControlHeight.DEFAULT.value}px;
            }}
            QLineEdit:focus {{
                border: {variables['border.focusRing']} solid {variables['color.border.focus']};
            }}
        """)
        self._cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {variables['color.surface.elevated']};
                color: {variables['color.text']};
                border: {variables['border.hairline']} solid {variables['color.border']};
                border-radius: {variables['radius.medium']};
                padding: 0 {Space.SPACE_300}px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {variables['color.surface.nested']}; }}
        """)
        self._primary_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {fill};
                color: {ink};
                border: none;
                border-radius: {variables['radius.medium']};
                padding: 0 {Space.SPACE_300}px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {fill}; border: 2px solid {variables['color.border.strong']}; }}
        """)


class DeleteConfirmationDialog(_ThemedDialog):
    """Confirm deleting a chat or a project.

    Args:
        theme_manager: The active theme manager.
        title: Name of the thing being deleted, shown in the message.
        parent: Optional Qt parent.
        kind: ``"chat"`` or ``"project"``.
    """

    def __init__(self, theme_manager: ThemeManager, title: str, parent=None, kind: str = "chat") -> None:
        super().__init__(
            theme_manager,
            f"Delete {kind}",
            f"Delete {kind}?",
            "Delete",
            destructive=True,
            size=(380, 190),
            parent=parent,
        )
        if kind == "project":
            text = (
                f'"{title}" will be deleted. Its chats are not lost — they move to '
                "the default project."
            )
        else:
            text = f'This will delete "{title}". This cannot be undone.'
        self._message_label = QLabel(text)
        self._message_label.setFont(to_qfont(style_for(TextRole.BODY)))
        self._message_label.setWordWrap(True)
        self._add_content(self._message_label)
        # Kept for callers that style/inspect it.
        self._delete_button = self._primary_button


class PromptDialog(_ThemedDialog):
    """Ask for a single line of text (rename a chat, name a project)."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        heading: str,
        initial: str = "",
        primary_text: str = "Save",
        placeholder: str = "",
        parent=None,
    ) -> None:
        super().__init__(
            theme_manager,
            heading,
            heading,
            primary_text,
            destructive=False,
            size=(380, 190),
            parent=parent,
        )
        self._edit = QLineEdit(initial)
        self._edit.setMaxLength(_MAX_NAME_CHARS)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setFont(to_qfont(style_for(TextRole.BODY)))
        self._edit.selectAll()
        self._edit.returnPressed.connect(self._accept_if_valid)
        self._add_content(self._edit)
        self._primary_button.clicked.disconnect()
        self._primary_button.clicked.connect(self._accept_if_valid)

    def value(self) -> str:
        """The entered text, trimmed."""
        return self._edit.text().strip()

    def _accept_if_valid(self) -> None:
        if self.value():
            self.accept()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._edit.setFocus()
        self._edit.selectAll()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


class _DotsButton(QPushButton):
    """A "⋯" button whose dots are painted, so every font/platform shows them."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dot_color = QColor("#888888")

    def set_dot_color(self, color: QColor) -> None:
        self._dot_color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)  # background / hover fill from the stylesheet
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._dot_color)
        radius = 1.8
        cy = self.height() / 2
        cx = self.width() / 2
        for dx in (-6, 0, 6):
            painter.drawEllipse(QPoint(int(cx + dx), int(cy)), radius, radius)


class _ElidedLabel(QLabel):
    """A single-line label that shows an ellipsis instead of overflowing."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._apply_elision()

    def setFullText(self, text: str) -> None:  # noqa: N802 (Qt style)
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(self.width(), 0)
        elided = (
            self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
            if width
            else self._full_text
        )
        super().setText(elided)


class _RowItem(QWidget):
    """One list row: a title plus a "⋯" button revealed on hover."""

    #: Emitted with (item id, the button) when "⋯" is clicked.
    menu_clicked = Signal(int, QWidget)

    def __init__(self, item_id: int, title: str, height: int, parent=None) -> None:
        super().__init__(parent)
        self._item_id = item_id
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip(title)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.SPACE_150, 0, Space.SPACE_050, 0)
        layout.setSpacing(Space.SPACE_050)

        self._title_label = _ElidedLabel(title)
        self._title_label.setFont(to_qfont(style_for(TextRole.BODY)))
        layout.addWidget(self._title_label, 1)

        self._menu_button = _DotsButton()
        self._menu_button.setFixedSize(30, 28)
        self._menu_button.setToolTip("Options")
        self._menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_button.clicked.connect(lambda: self.menu_clicked.emit(self._item_id, self._menu_button))
        self._menu_button.hide()  # revealed on hover, like ChatGPT
        layout.addWidget(self._menu_button)

    @property
    def item_id(self) -> int:
        return self._item_id

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._menu_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Keep the button while its menu is open so the click isn't orphaned.
        if not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._menu_button.hide()
        super().leaveEvent(event)

    def _apply_theme(self, theme: Theme) -> None:
        variables = qss_variables(theme)
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {variables['color.text']}; background: transparent; }}"
        )
        self._menu_button.set_dot_color(to_qcolor(theme.palette.text.secondary))
        self._menu_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {variables['radius.small']};
            }}
            QPushButton:hover {{ background-color: {variables['color.surface.elevated']}; }}
        """)


class ConversationListItem(_RowItem):
    """A chat row."""

    def __init__(self, conversation_id: int, title: str, parent=None) -> None:
        super().__init__(conversation_id, title, _ROW_HEIGHT_PX, parent)

    @property
    def conversation_id(self) -> int:
        return self._item_id


class ProjectListItem(_RowItem):
    """A project row."""

    def __init__(self, project_id: int, name: str, parent=None) -> None:
        super().__init__(project_id, name, _PROJECT_ROW_HEIGHT_PX, parent)

    @property
    def project_id(self) -> int:
        return self._item_id


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


class NavigationSidebar(QWidget):
    """The collapsible rail: new chat, projects, and the project's chats.

    Emits:
        conversation_selected: int - a chat was clicked
        conversation_deleted: int - deleting a chat was confirmed
        conversation_renamed: (int, str) - a chat was renamed
        conversation_moved: (int, int) - a chat was moved to another project
        new_chat_requested: () - the New chat button was clicked
        project_changed: int - the selected project changed
        project_created: str - a new project was named
        conversation_moved_to_new_project: (int, str) - a chat moved into a
            project that must first be created with the given name
        project_renamed: (int, str) - a project was renamed
        project_deleted: int - deleting a project was confirmed
        mode_changed: int - compact/expanded changed
        visibility_changed: bool - shown (True) or hidden (False)
    """

    conversation_selected = Signal(int)
    conversation_deleted = Signal(int)
    conversation_renamed = Signal(int, str)
    conversation_moved = Signal(int, int)
    new_chat_requested = Signal()
    project_changed = Signal(int)
    project_created = Signal(str)
    conversation_moved_to_new_project = Signal(int, str)
    project_renamed = Signal(int, str)
    project_deleted = Signal(int)
    mode_changed = Signal(int)
    visibility_changed = Signal(bool)

    def __init__(self, theme_manager: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._mode = SidebarMode.EXPANDED
        self._conversations: list[dict] = []
        self._projects: list[dict] = []
        self._current_project_id: int | None = None
        self._selected_conversation_id: int | None = None
        self._collapsed = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(LAYOUT.sidebar_expanded)

        self._width_animation = QPropertyAnimation(self, b"minimumWidth")
        self._width_animation.setDuration(200)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_animation.finished.connect(self._on_animation_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- New chat ----------------------------------------------------------
        self._header = QWidget()
        self._header.setFixedHeight(LAYOUT.header_height)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(Space.SPACE_100, Space.SPACE_100, Space.SPACE_100, Space.SPACE_050)
        self._new_chat_button = QPushButton("✎   New chat")
        self._new_chat_button.setFixedHeight(40)
        self._new_chat_button.setToolTip("New chat")
        self._new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_chat_button.clicked.connect(self.new_chat_requested.emit)
        header_layout.addWidget(self._new_chat_button, 1)
        layout.addWidget(self._header)

        # -- Projects ----------------------------------------------------------
        self._project_section = QWidget()
        proj_layout = QVBoxLayout(self._project_section)
        proj_layout.setContentsMargins(0, 0, 0, 0)
        proj_layout.setSpacing(0)

        proj_header = QHBoxLayout()
        proj_header.setContentsMargins(Space.SPACE_200, Space.SPACE_100, Space.SPACE_100, Space.SPACE_050)
        self._project_caption = QLabel("Projects")
        self._project_caption.setFont(to_qfont(style_for(TextRole.CAPTION)))
        proj_header.addWidget(self._project_caption)
        proj_header.addStretch(1)
        self._new_project_button = QPushButton("+")
        self._new_project_button.setFixedSize(28, 28)
        self._new_project_button.setToolTip("New project")
        self._new_project_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_project_button.clicked.connect(self._on_new_project_clicked)
        proj_header.addWidget(self._new_project_button)
        proj_layout.addLayout(proj_header)

        self._project_list = self._make_list()
        self._project_list.itemClicked.connect(self._on_project_item_clicked)
        proj_layout.addWidget(self._project_list)
        layout.addWidget(self._project_section)

        # -- Chats of the selected project ----------------------------------------
        self._caption = QLabel("Chats")
        self._caption.setFont(to_qfont(style_for(TextRole.CAPTION)))
        self._caption.setContentsMargins(Space.SPACE_200, Space.SPACE_150, Space.SPACE_100, Space.SPACE_050)
        layout.addWidget(self._caption)

        self._conversation_list = self._make_list()
        self._conversation_list.itemClicked.connect(self._on_conversation_clicked)
        layout.addWidget(self._conversation_list, 1)

        # -- Footer ----------------------------------------------------------------
        self._footer = QWidget()
        self._footer.setFixedHeight(44)
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(Space.SPACE_200, Space.SPACE_050, Space.SPACE_200, Space.SPACE_050)
        self._mode_toggle = QPushButton("◀")
        self._mode_toggle.setFixedSize(32, 32)
        self._mode_toggle.setToolTip("Collapse sidebar")
        self._mode_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_toggle.clicked.connect(self._toggle_mode)
        footer_layout.addWidget(self._mode_toggle)
        footer_layout.addStretch(1)
        layout.addWidget(self._footer)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @staticmethod
    def _make_list() -> QListWidget:
        widget = QListWidget()
        widget.setFrameShape(QListWidget.Shape.NoFrame)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        return widget

    # -- modes / collapse ------------------------------------------------------

    def _toggle_mode(self) -> None:
        self.set_mode(SidebarMode.COMPACT if self._mode == SidebarMode.EXPANDED else SidebarMode.EXPANDED)

    def set_mode(self, mode: int) -> None:
        """Set the sidebar display mode."""
        if mode == self._mode:
            return
        self._mode = mode
        compact = mode == SidebarMode.COMPACT
        for widget in (self._project_section, self._caption):
            widget.setVisible(not compact)
        self._new_chat_button.setText("✎" if compact else "✎   New chat")
        self._mode_toggle.setText("▶" if compact else "◀")
        self._mode_toggle.setToolTip("Expand sidebar" if compact else "Collapse sidebar")
        self._animate_width(LAYOUT.sidebar_compact if compact else LAYOUT.sidebar_expanded)
        self.mode_changed.emit(mode)

    def toggle_collapse(self) -> None:
        """Toggle between fully visible and fully hidden."""
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self) -> None:
        """Animate sidebar to hidden state."""
        if self._collapsed:
            return
        self._collapsed = True
        self._animate_width(0)
        self.visibility_changed.emit(False)

    def expand(self) -> None:
        """Animate sidebar to visible state."""
        if not self._collapsed:
            return
        self._collapsed = False
        target = LAYOUT.sidebar_compact if self._mode == SidebarMode.COMPACT else LAYOUT.sidebar_expanded
        self._animate_width(target)
        self.visibility_changed.emit(True)

    def _animate_width(self, target_width: int) -> None:
        self._width_animation.stop()
        self._width_animation.setStartValue(self.width())
        self._width_animation.setEndValue(target_width)
        self.setMinimumWidth(target_width)
        self.setMaximumWidth(target_width)
        self._width_animation.start()

    def _on_animation_finished(self) -> None:
        if self._collapsed:
            self.hide()
        else:
            self.show()

    # -- chats -------------------------------------------------------------------

    @staticmethod
    def _display_title(conv: dict) -> str:
        """The row title: the saved title, else one derived from the first question."""
        from aashi.ui.services.titles import heuristic_title

        title = (conv.get("title") or "").strip()
        if title:
            return title
        return heuristic_title(conv.get("first_user_message") or "", fallback="New chat")

    def set_conversations(self, conversations: list[dict], project_id: int | None = None) -> None:
        """Set the chat list for the current project."""
        self._conversations = conversations
        self._conversation_list.clear()
        for conv in conversations:
            title = self._display_title(conv)
            shown = title[:1].upper() if self._mode == SidebarMode.COMPACT else title
            row = ConversationListItem(conv["id"], shown)
            row.setToolTip(title)
            row.menu_clicked.connect(self._on_chat_menu_requested)
            row._apply_theme(self._theme_manager.theme)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, conv["id"])
            item.setSizeHint(QSize(0, _ROW_HEIGHT_PX))
            self._conversation_list.addItem(item)
            self._conversation_list.setItemWidget(item, row)
        self._update_selection()

    def _on_conversation_clicked(self, item: QListWidgetItem) -> None:
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id is not None:
            self._selected_conversation_id = conv_id
            self._update_selection()
            self.conversation_selected.emit(conv_id)

    def _update_selection(self) -> None:
        for i in range(self._conversation_list.count()):
            item = self._conversation_list.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) == self._selected_conversation_id)

    def select_conversation(self, conversation_id: int | None) -> None:
        """Programmatically select a chat (``None`` clears the selection)."""
        self._selected_conversation_id = conversation_id
        self._update_selection()

    def _conversation_title(self, conversation_id: int) -> str:
        for conv in self._conversations:
            if conv["id"] == conversation_id:
                return self._display_title(conv)
        return "this chat"

    # -- chat menu: rename / move / delete -------------------------------------------

    def _on_chat_menu_requested(self, conversation_id: int, anchor: QWidget) -> None:
        menu = self._build_chat_menu(conversation_id)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))

    def _build_chat_menu(self, conversation_id: int) -> QMenu:
        """Build (without showing) the ⋯ menu of a chat."""
        menu = self._new_menu()
        menu.addAction("Rename").triggered.connect(lambda: self._rename_chat(conversation_id))

        current = self._project_of_conversation(conversation_id)
        move = self._new_menu("Move to project", parent=menu)
        for project in self._projects:
            action = move.addAction(project["name"] or "Unnamed project")
            action.setCheckable(True)
            action.setChecked(project["id"] == current)
            if project["id"] != current:
                action.triggered.connect(
                    lambda _=False, pid=project["id"]: self.conversation_moved.emit(conversation_id, pid)
                )
        move.addSeparator()
        move.addAction("New project…").triggered.connect(
            lambda: self._new_project_then_move(conversation_id)
        )
        menu.addMenu(move)
        menu.addSeparator()
        self._add_danger_action(menu, "Delete", lambda: self._on_delete_conversation_requested(conversation_id))
        return menu

    def _project_of_conversation(self, conversation_id: int) -> int | None:
        for conv in self._conversations:
            if conv["id"] == conversation_id:
                return conv.get("project_id", self._current_project_id)
        return self._current_project_id

    def _rename_chat(self, conversation_id: int) -> None:
        dialog = PromptDialog(
            self._theme_manager,
            "Rename chat",
            initial=self._conversation_title(conversation_id),
            primary_text="Save",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.value():
            self.conversation_renamed.emit(conversation_id, dialog.value())

    def _new_project_then_move(self, conversation_id: int) -> None:
        name = self._ask_project_name()
        if name:
            self.conversation_moved_to_new_project.emit(conversation_id, name)

    def _on_delete_conversation_requested(self, conversation_id: int) -> None:
        dialog = DeleteConfirmationDialog(
            self._theme_manager, self._conversation_title(conversation_id), self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.conversation_deleted.emit(conversation_id)

    # -- projects -----------------------------------------------------------------------

    def set_projects(self, projects: list[dict], current_project_id: int | None = None) -> None:
        """Set the available projects (oldest first, so the order is stable)."""
        self._projects = sorted(projects, key=lambda p: (p.get("created_at") or 0, p["id"]))
        self._rebuild_project_rows()
        if self._projects and current_project_id is not None:
            self.set_current_project(current_project_id)
        elif self._projects and self._current_project_id is None:
            self.set_current_project(self._projects[0]["id"])
        else:
            self._update_project_selection()

    def _rebuild_project_rows(self) -> None:
        self._project_list.clear()
        for project in self._projects:
            name = project["name"] or "Unnamed project"
            row = ProjectListItem(project["id"], name)
            row.menu_clicked.connect(self._on_project_menu_requested)
            row._apply_theme(self._theme_manager.theme)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, project["id"])
            item.setSizeHint(QSize(0, _PROJECT_ROW_HEIGHT_PX))
            self._project_list.addItem(item)
            self._project_list.setItemWidget(item, row)
        rows = min(max(len(self._projects), 1), _PROJECT_ROWS_VISIBLE)
        self._project_list.setFixedHeight(rows * (_PROJECT_ROW_HEIGHT_PX + 2) + 4)
        self._update_project_selection()

    def _update_project_selection(self) -> None:
        for i in range(self._project_list.count()):
            item = self._project_list.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) == self._current_project_id)

    def _project_name(self, project_id: int) -> str:
        for project in self._projects:
            if project["id"] == project_id:
                return project["name"] or "Unnamed project"
        return "this project"

    def set_current_project(self, project_id: int) -> None:
        """Select a project and show its chats."""
        if self._current_project_id == project_id:
            self._update_project_selection()
            return
        self._current_project_id = project_id
        self._caption.setText(f"Chats in {self._project_name(project_id)}")
        self._update_project_selection()
        self.project_changed.emit(project_id)

    def refresh_caption(self) -> None:
        """Re-read the project name into the chats caption (after a rename)."""
        if self._current_project_id is not None:
            self._caption.setText(f"Chats in {self._project_name(self._current_project_id)}")

    def _on_project_item_clicked(self, item: QListWidgetItem) -> None:
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id is not None:
            self.set_current_project(project_id)

    def _ask_project_name(self) -> str:
        dialog = PromptDialog(
            self._theme_manager,
            "New project",
            primary_text="Create",
            placeholder="Project name",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.value()
        return ""

    def _on_new_project_clicked(self) -> None:
        name = self._ask_project_name()
        if name:
            self.project_created.emit(name)

    def _on_project_menu_requested(self, project_id: int, anchor: QWidget) -> None:
        menu = self._build_project_menu(project_id)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))

    def _build_project_menu(self, project_id: int) -> QMenu:
        """Build (without showing) the ⋯ menu of a project."""
        menu = self._new_menu()
        menu.addAction("Rename").triggered.connect(lambda: self._rename_project(project_id))
        # The oldest project is the default home for chats and cannot be deleted.
        if self._projects and self._projects[0]["id"] != project_id:
            menu.addSeparator()
            self._add_danger_action(menu, "Delete", lambda: self._delete_project(project_id))
        return menu

    def _rename_project(self, project_id: int) -> None:
        dialog = PromptDialog(
            self._theme_manager,
            "Rename project",
            initial=self._project_name(project_id),
            primary_text="Save",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.value():
            self.project_renamed.emit(project_id, dialog.value())

    def _delete_project(self, project_id: int) -> None:
        dialog = DeleteConfirmationDialog(
            self._theme_manager, self._project_name(project_id), self, kind="project"
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.project_deleted.emit(project_id)

    # -- menus -----------------------------------------------------------------------------

    def _menu_stylesheet(self) -> str:
        v = qss_variables(self._theme_manager.theme)
        return f"""
            QMenu {{
                background-color: {v['color.surface.elevated']};
                color: {v['color.text']};
                border: {v['border.hairline']} solid {v['color.border.strong']};
                border-radius: {v['radius.large']};
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 28px 8px 14px;
                border-radius: {v['radius.small']};
                background: transparent;
            }}
            QMenu::item:selected {{ background-color: {v['color.surface.nested']}; }}
            QMenu::indicator {{ width: 14px; height: 14px; }}
            QMenu::separator {{
                height: 1px;
                background: {v['color.border']};
                margin: 4px 8px;
            }}
        """

    def _new_menu(self, title: str = "", parent: QWidget | None = None) -> QMenu:
        menu = QMenu(title, parent or self)
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        menu.setStyleSheet(self._menu_stylesheet())
        return menu

    def _add_danger_action(self, menu: QMenu, text: str, callback) -> None:
        """Add a red menu entry (QMenu items cannot be coloured individually)."""
        v = qss_variables(self._theme_manager.theme)
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 28px 8px 14px;
                background: transparent;
                color: {v['color.danger.text']};
                border: none;
                border-radius: {v['radius.small']};
            }}
            QPushButton:hover {{ background-color: {v['color.danger.tint']}; }}
        """)
        button.setFont(to_qfont(style_for(TextRole.BODY)))

        def run() -> None:
            menu.close()
            callback()

        button.clicked.connect(run)
        action = QWidgetAction(menu)
        action.setDefaultWidget(button)
        menu.addAction(action)

    # -- styling --------------------------------------------------------------------------------

    def _restyle(self, *_: object) -> None:
        theme = self._theme_manager.theme
        v = qss_variables(theme)
        edge = v["color.border.strong"] if theme.high_contrast else v["color.border"]

        self.setStyleSheet(f"""
            NavigationSidebar {{
                background-color: {v['color.surface']};
                border-right: {v['border.hairline']} solid {edge};
            }}
            NavigationSidebar QWidget {{ background: transparent; }}
            QLabel {{ color: {v['color.text']}; background: transparent; border: none; }}
            QPushButton {{
                background-color: transparent;
                color: {v['color.text']};
                border: none;
                border-radius: {v['radius.medium']};
            }}
            QPushButton:hover {{ background-color: {v['color.surface.nested']}; }}
            QPushButton:pressed {{ background-color: {v['color.surface.elevated']}; }}
            QListWidget {{
                background-color: transparent;
                border: none;
                outline: none;
                padding: 0 {Space.SPACE_100}px;
            }}
            QListWidget::item {{
                margin: 1px 0;
                padding: 0;
                border-radius: {v['radius.medium']};
                color: {v['color.text']};
            }}
            QListWidget::item:hover {{ background-color: {v['color.surface.elevated']}; }}
            QListWidget::item:selected, QListWidget::item:selected:!active {{
                background-color: {v['color.surface.nested']};
                color: {v['color.text']};
            }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{
                background: {v['color.border.strong']};
                border-radius: 4px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        for list_widget in (self._conversation_list, self._project_list):
            for i in range(list_widget.count()):
                row = list_widget.itemWidget(list_widget.item(i))
                if isinstance(row, _RowItem):
                    row._apply_theme(theme)

        for region in (self._header, self._project_section, self._footer):
            region.setStyleSheet("QWidget { background: transparent; }")

        self._new_chat_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {v['color.text']};
                border: {v['border.hairline']} solid {v['color.border']};
                border-radius: {v['radius.large']};
                text-align: left;
                padding: 0 {Space.SPACE_150}px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {v['color.surface.nested']}; }}
            QPushButton:pressed {{ background-color: {v['color.surface.elevated']}; }}
        """)
        self._new_project_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {v['color.text.secondary']};
                border: none;
                border-radius: {v['radius.medium']};
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: {v['color.surface.nested']};
                color: {v['color.text']};
            }}
        """)
        self._mode_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {v['color.text.secondary']};
                border: none;
                border-radius: {v['radius.medium']};
            }}
            QPushButton:hover {{
                background-color: {v['color.surface.nested']};
                color: {v['color.text']};
            }}
        """)
        for caption in (self._project_caption, self._caption):
            caption.setStyleSheet(f"color: {v['color.text.tertiary']}; background: transparent;")
