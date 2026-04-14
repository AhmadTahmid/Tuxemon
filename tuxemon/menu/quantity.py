# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, ClassVar

from tuxemon.item.stock import INFINITE_ITEMS
from tuxemon.locale.locale import T
from tuxemon.menu.formatter import CurrencyFormatter, QuantityFormatter
from tuxemon.menu.interface import MenuItem
from tuxemon.menu.menu import Menu
from tuxemon.platform.const import buttons, intentions
from tuxemon.platform.events import PlayerInput

if TYPE_CHECKING:
    from tuxemon.base_client import BaseClient

logger = logging.getLogger(__name__)

QUANTITY_INCREMENT = 1
QUANTITY_PAGE_INCREMENT = 10
MIN_QUANTITY = 1
REPEAT_DELAY = 0.3  # seconds before repeat starts
REPEAT_INTERVAL = 0.1  # seconds between repeats

QUANTITY_DELTAS = {
    buttons.UP: +QUANTITY_INCREMENT,
    buttons.DOWN: -QUANTITY_INCREMENT,
    buttons.RIGHT: +QUANTITY_PAGE_INCREMENT,
    buttons.LEFT: -QUANTITY_PAGE_INCREMENT,
}


class QuantityMenu(Menu[None]):
    """Menu used to select quantities."""

    name: ClassVar[str] = "QuantityMenu"

    def __init__(
        self,
        client: BaseClient,
        callback: Callable[[int], None],
        quantity: int = 1,
        max_quantity: int | None = None,
        shrink_to_items: bool = False,
        price: int = 0,
        cost: int = 0,
        wallet_money: int = 0,
        currency_formatter: CurrencyFormatter | None = None,
        quantity_formatter: QuantityFormatter | None = None,
        label: Callable[[int], str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client=client, **kwargs)

        self.quantity = quantity
        self.max_quantity = (
            max_quantity if max_quantity != INFINITE_ITEMS else None
        )

        self.callback = callback
        self.shrink_to_items = shrink_to_items

        self.price = price
        self.cost = cost
        self.wallet_money = wallet_money

        self.currency_formatter = currency_formatter or CurrencyFormatter()
        self.quantity_formatter = quantity_formatter or QuantityFormatter()
        self.label = label or self.quantity_formatter.format

    def process_event(self, event: PlayerInput) -> PlayerInput | None:
        if event.pressed:
            if event.button in (
                buttons.B,
                buttons.BACK,
                intentions.MENU_CANCEL,
            ):
                self.close()
                self.callback(0)
                return None

            if event.button == buttons.A:
                self.menu_select_sound.play()
                self.close()
                self.callback(self.quantity)
                return None

            self._apply_button(event.button)

        elif event.held and event.is_held(REPEAT_DELAY):
            self._apply_button(event.button)

        return None

    def _apply_button(self, button: int) -> None:
        delta = QUANTITY_DELTAS.get(button)
        if delta is None:
            return

        self.adjust_quantity(delta)

    def adjust_quantity(self, delta: int) -> None:
        self.quantity += delta
        self._clamp_quantity()
        self.reload_items()

    def _clamp_quantity(self) -> None:
        if self.max_quantity is None:
            self.quantity = max(MIN_QUANTITY, self.quantity)
        else:
            self.quantity = max(
                MIN_QUANTITY, min(self.quantity, self.max_quantity)
            )

    def calculate_total(self, value: int) -> int:
        return self.quantity * value

    def make_item(self, label: str) -> MenuItem[None]:
        return MenuItem(self.shadow_text(label), label, None, None)

    def initialize_items(self) -> Iterable[MenuItem[None]]:
        yield self.make_item(self.label(self.quantity))

    def show_money(self) -> Iterable[MenuItem[None]]:
        formatted = self.currency_formatter.format(self.wallet_money)
        label = f"{T.translate('wallet')}: {formatted}"
        yield self.make_item(label)

    def get_value_label(self) -> str:
        """Subclasses override to show price/cost."""
        return ""


class QuantityAndPriceMenu(QuantityMenu):
    """Menu used to select quantities and show price."""

    name: ClassVar[str] = "QuantityAndPriceMenu"

    def __init__(self, client: BaseClient, *args: Any, **kwargs: Any) -> None:
        super().__init__(client, *args, **kwargs)

    def get_value_label(self) -> str:
        price = self.calculate_total(self.price)
        if price == 0:
            return T.translate("shop_buy_free")
        if price > self.wallet_money:
            return T.translate("shop_buy_too_expensive")
        return self.currency_formatter.format(price)

    def initialize_items(self) -> Iterable[MenuItem[None]]:
        yield from self.show_money()
        yield from super().initialize_items()
        yield self.make_item(self.get_value_label())


class QuantityAndCostMenu(QuantityMenu):
    """Menu used to select quantities and show cost."""

    name: ClassVar[str] = "QuantityAndCostMenu"

    def __init__(self, client: BaseClient, *args: Any, **kwargs: Any) -> None:
        super().__init__(client, *args, **kwargs)

    def get_value_label(self) -> str:
        return self.currency_formatter.format(self.calculate_total(self.cost))

    def initialize_items(self) -> Iterable[MenuItem[None]]:
        yield from self.show_money()
        yield from super().initialize_items()
        yield self.make_item(self.get_value_label())
