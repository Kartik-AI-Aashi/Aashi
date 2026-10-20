"""The sidebar lists real chats, names them, highlights the open one."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtWidgets import QDialog  # noqa: E402

from aashi.paths import resolve_paths  # noqa: E402
from aashi.storage.database import ConversationDatabase  # noqa: E402
from aashi.ui.components import navigation  # noqa: E402
from aashi.ui.services import titles  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.windows import chat_window  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """A chat window on its own empty database, with a stubbed AI reply."""
    paths = resolve_paths(user_data_dir=tmp_path, bundle_root=tmp_path, config_dir=tmp_path)
    paths.ensure_user_directories()
    db = ConversationDatabase(paths)
    monkeypatch.setattr(chat_window, "resolve_paths", lambda: paths)
    monkeypatch.setattr(chat_window, "get_database", lambda _p=None: db)
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda _m: "Sure.")
    win = chat_window.AashiChatWindow(ThemeManager())
    qtbot.addWidget(win)
    win.show()
    yield win
    win._finish_typewriter()
    db.close()


def _rows(win) -> list[str]:
    lst = win._sidebar._conversation_list
    return [lst.itemWidget(lst.item(i))._title_label._full_text for i in range(lst.count())]


def _ask(win, qtbot, text: str) -> None:
    win.input.setText(text)
    win._submit_message()
    qtbot.waitUntil(lambda: win._typewriter_timer is None and win._thinking_bubble is None, timeout=5000)
    win._finish_typewriter()


def test_launch_and_new_chat_leave_no_blank_entries(window, qtbot) -> None:
    assert _rows(window) == []
    window._on_new_chat_requested()
    window._on_new_chat_requested()
    assert _rows(window) == []


def test_first_question_names_the_chat_and_highlights_it(window, qtbot) -> None:
    _ask(window, qtbot, "Can you explain how a binary search works?")
    assert _rows(window) == ["How a Binary Search Works"]
    assert window._sidebar._selected_conversation_id == window._conversation_id
    row = window._sidebar._conversation_list.itemWidget(window._sidebar._conversation_list.item(0))
    assert row.height() >= 32  # rows are tall enough to read


def test_follow_up_questions_do_not_rename_the_chat(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    _ask(window, qtbot, "and what about germany")
    assert _rows(window) == ["Capital of France"]


def test_each_new_chat_gets_its_own_row_and_newest_is_first(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    window._on_new_chat_requested()
    _ask(window, qtbot, "how do i center a div in css")
    assert _rows(window) == ["Center a Div in Css", "Capital of France"]


def test_clicking_a_chat_opens_it(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    window._on_new_chat_requested()
    _ask(window, qtbot, "how do i center a div in css")
    lst = window._sidebar._conversation_list
    lst.itemClicked.emit(lst.item(1))  # "Capital of France"
    assert window._messages[0].text.startswith("what is the capital of france")
    assert window._sidebar._selected_conversation_id == window._conversation_id


def test_ai_title_replaces_the_instant_title(window, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(titles, "AI_TITLES_ENABLED", True)
    monkeypatch.setattr(titles.local_ai, "fetch_response_hybrid", lambda _p: "Binary Search Basics")
    window.input.setText("Can you explain how a binary search works?")
    window._submit_message()
    qtbot.waitUntil(lambda: _rows(window) == ["Binary Search Basics"], timeout=5000)


def test_deleting_a_chat_removes_its_row(window, qtbot, monkeypatch) -> None:
    _ask(window, qtbot, "what is the capital of france")
    monkeypatch.setattr(
        navigation.DeleteConfirmationDialog, "exec", lambda _self: QDialog.DialogCode.Accepted
    )
    window._sidebar._on_delete_conversation_requested(window._conversation_id)
    assert _rows(window) == []
    assert window.message_count == 0


def test_delete_dialog_builds_without_error(qtbot) -> None:
    dialog = navigation.DeleteConfirmationDialog(ThemeManager(), "Some chat")
    qtbot.addWidget(dialog)
    assert dialog._delete_button.text() == "Delete"


def test_untitled_legacy_chats_are_named_from_their_first_question(qtbot) -> None:
    title = navigation.NavigationSidebar._display_title(
        {"title": "", "first_user_message": "what is the capital of france"}
    )
    assert title == "Capital of France"


# --- projects, rename, move, menus ------------------------------------------------


def _project_rows(win) -> list[str]:
    lst = win._sidebar._project_list
    return [lst.itemWidget(lst.item(i))._title_label._full_text for i in range(lst.count())]


def test_delete_button_text_is_visible_and_not_the_fill_colour(qtbot) -> None:
    dialog = navigation.DeleteConfirmationDialog(ThemeManager(), "Some chat")
    qtbot.addWidget(dialog)
    sheet = dialog._delete_button.styleSheet()
    import re

    background = re.search(r"background-color:\s*([^;]+);", sheet).group(1).strip()
    colour = re.search(r"(?<![-\w])color:\s*([^;]+);", sheet).group(1).strip()
    assert dialog._delete_button.text() == "Delete"
    assert background != colour  # red text on a red fill was invisible


def test_row_menu_button_opens_a_menu_instead_of_the_delete_dialog(window, qtbot, monkeypatch) -> None:
    _ask(window, qtbot, "what is the capital of france")
    sidebar = window._sidebar
    opened: list[str] = []
    monkeypatch.setattr(
        navigation.DeleteConfirmationDialog, "exec", lambda _s: opened.append("delete") or 0
    )

    class _FakeMenu:  # a real QMenu.exec() would block the test run
        def exec(self, _pos=None) -> None:
            opened.append("menu")

    monkeypatch.setattr(
        navigation.NavigationSidebar, "_build_chat_menu", lambda _self, _cid: _FakeMenu()
    )
    row = sidebar._conversation_list.itemWidget(sidebar._conversation_list.item(0))
    row._menu_button.click()
    assert opened == ["menu"]


def test_chat_menu_has_rename_move_and_delete(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    menu = window._sidebar._build_chat_menu(window._conversation_id)
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[:2] == ["Rename", "Move to project"]
    assert any(a.defaultWidget() and a.defaultWidget().text() == "Delete"
               for a in menu.actions() if hasattr(a, "defaultWidget"))


def test_renaming_a_chat_keeps_its_place_in_the_list(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    first_id = window._conversation_id
    window._on_new_chat_requested()
    _ask(window, qtbot, "how do i center a div in css")
    window._sidebar.conversation_renamed.emit(first_id, "Geography quiz")
    assert _rows(window) == ["Center a Div in Css", "Geography quiz"]


def test_creating_a_project_opens_an_empty_chat_inside_it(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    window._on_project_created("College Notes")
    assert _project_rows(window) == ["Default Project", "College Notes"]
    assert _rows(window) == []  # the new project has no chats yet
    assert window.message_count == 0
    _ask(window, qtbot, "what is a binary tree")
    assert _rows(window) == ["Binary Tree"]


def test_chats_are_separated_per_project(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    window._on_project_created("College Notes")
    _ask(window, qtbot, "what is a binary tree")
    default_id = window._sidebar._projects[0]["id"]
    window._sidebar.set_current_project(default_id)
    assert _rows(window) == ["Capital of France"]


def test_moving_a_chat_to_another_project(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    chat_id = window._conversation_id
    window._on_project_created("College Notes")
    target = window._sidebar._projects[1]["id"]
    window._sidebar.set_current_project(window._sidebar._projects[0]["id"])
    window._on_conversation_moved(chat_id, target)
    assert _rows(window) == []  # it left the default project
    window._sidebar.set_current_project(target)
    assert _rows(window) == ["Capital of France"]


def test_moving_the_open_chat_follows_it_into_the_project(window, qtbot) -> None:
    _ask(window, qtbot, "what is the capital of france")
    window._on_project_created("College Notes")
    window._sidebar.set_current_project(window._sidebar._projects[0]["id"])
    chat = window._sidebar._conversation_list.item(0)
    window._sidebar._conversation_list.itemClicked.emit(chat)
    window._on_moved_to_new_project(window._conversation_id, "Homework")
    assert _project_rows(window)[-1] == "Homework"
    assert _rows(window) == ["Capital of France"]
    assert window._sidebar._selected_conversation_id == window._conversation_id


def test_renaming_a_project_updates_the_list_and_caption(window, qtbot) -> None:
    window._on_project_created("College Notes")
    pid = window._sidebar._projects[1]["id"]
    window._on_project_renamed(pid, "University")
    assert _project_rows(window) == ["Default Project", "University"]
    assert window._sidebar._caption.text() == "Chats in University"


def test_deleting_a_project_moves_its_chats_to_the_default_project(window, qtbot) -> None:
    window._on_project_created("College Notes")
    _ask(window, qtbot, "what is a binary tree")
    pid = window._sidebar._projects[1]["id"]
    window._on_project_deleted(pid)
    assert _project_rows(window) == ["Default Project"]
    assert _rows(window) == ["Binary Tree"]  # not lost


def test_the_default_project_cannot_be_deleted(window, qtbot) -> None:
    default_id = window._sidebar._projects[0]["id"]
    window._on_project_deleted(default_id)
    assert _project_rows(window) == ["Default Project"]
    menu = window._sidebar._build_project_menu(default_id)
    assert [a.text() for a in menu.actions() if a.text()] == ["Rename"]


def test_prompt_dialog_requires_a_non_blank_name(qtbot) -> None:
    dialog = navigation.PromptDialog(ThemeManager(), "New project", primary_text="Create")
    qtbot.addWidget(dialog)
    dialog._edit.setText("   ")
    dialog._primary_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog._edit.setText("  Trip  ")
    dialog._primary_button.click()
    assert dialog.value() == "Trip"
    assert dialog.result() == QDialog.DialogCode.Accepted
