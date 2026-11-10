"""Small Streamlit presentation helpers that avoid heavy dataframe serialization."""

from collections.abc import Sequence
from html import escape
from typing import Any

import streamlit as st

from utils.performance import measure_function


@measure_function("ui.render_static_table")
def render_static_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """Render small read-only tables as Markdown without importing dataframe engines."""
    if not headers:
        return

    def cell(value: Any) -> str:
        return escape(" ".join(str(value).split())).replace("|", "\\|")

    table_lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    table_lines.extend(
        "| " + " | ".join(cell(value) for value in row) + " |"
        for row in rows
    )
    st.markdown("\n".join(table_lines))
