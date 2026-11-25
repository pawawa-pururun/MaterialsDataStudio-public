"""Visual selectors drawn from the same marker paths/dashes as graph rendering."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QProxyStyle, QStyle

from materials_data_studio.tools.pxp_render import _DASH_PATTERNS
from materials_data_studio.ui.preview_assets import pixels_icon, preview_icon


class _ListPopupStyle(QProxyStyle):
    """Use a bounded scrollable list rather than a screen-height native menu."""

    def styleHint(self, hint: QStyle.StyleHint, option=None, widget=None, returnData=None) -> int:
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

@lru_cache(maxsize=512)
def style_icon(kind: str, number: int, dark: bool = False,
               pattern: tuple[float, ...] | None = None) -> QIcon:
    custom = kind == "line" and number and pattern and pattern != _DASH_PATTERNS.get(number, (4, 4))
    icon = None if custom else preview_icon(f"{kind}:{number}:{'dark' if dark else 'light'}")
    if icon is not None:
        return icon
    from materials_data_studio.tools.preview_render import style_pixels

    return pixels_icon(style_pixels(kind, number, dark, pattern))


def visual_choices(kind: str) -> list[tuple[str, int]]:
    if kind == "line":
        return [("Solid" if i == 0 else f"Pattern {i}", i) for i in range(18)]
    labels = {0: "+", 1: "×", 2: "✳", 5: "□", 6: "△", 7: "◇", 8: "○", 16: "■", 17: "▲", 18: "◆", 19: "●"}
    return [(labels.get(i, "Symbol") + f"  ({i})", i) for i in range(63)]


def visual_combo(kind: str, value: int | None, dark: bool = False,
                 patterns: tuple[tuple[int, tuple[float, ...]], ...] = ()) -> QComboBox:
    combo = QComboBox()
    popup_style = _ListPopupStyle("Fusion")
    popup_style.setParent(combo)
    combo.setStyle(popup_style)
    combo.setIconSize(QSize(96, 28))
    combo.setMaxVisibleItems(14)
    combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    for text, number in visual_choices(kind):
        combo.addItem(style_icon(kind, number, dark, dict(patterns).get(number)), text, number)
    combo.setCurrentIndex(max(0, combo.findData(value or 0)))
    return combo
