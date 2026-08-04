from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .domain import CostRule, MarketRule, MarketState, Side, SimFill, SimOrder, SimOrderStatus, SimOrderType, SimulationBar
from .errors import MissingRule


class BrokerSimulator:
    @staticmethod
    def market_rule(rules: tuple[MarketRule, ...], market: str, bar: SimulationBar) -> MarketRule:
        matches = [rule for rule in rules if rule.applies(market, bar.market_time.date())]
        if len(matches) != 1:
            raise MissingRule(f"expected one market rule for {market} at {bar.market_time.date()}")
        return matches[0]

    @staticmethod
    def cost_rule(rules: tuple[CostRule, ...], market: str, bar: SimulationBar) -> CostRule:
        matches = [rule for rule in rules if rule.applies(market, bar.market_time.date())]
        if len(matches) != 1:
            raise MissingRule(f"expected one cost rule for {market} at {bar.market_time.date()}")
        return matches[0]

    def match(self, order: SimOrder, bar: SimulationBar, bar_sequence: int, market_rule: MarketRule, cost_rule: CostRule, max_participation: Decimal, sellable_quantity: int, available_cash: Decimal) -> tuple[SimOrder, SimFill | None, str | None]:
        if order.status not in (SimOrderStatus.OPEN, SimOrderStatus.PARTIALLY_FILLED):
            return order, None, "ORDER_NOT_OPEN"
        if bar.instrument_id != order.instrument_id or bar_sequence < order.eligible_after_bar_sequence or bar.market_time <= order.submitted_at:
            return order, None, "NOT_YET_ELIGIBLE"
        if bar.state is MarketState.SUSPENDED:
            return order, None, "SUSPENDED"
        if bar.volume == 0:
            return order, None, "NO_VOLUME"
        if order.side is Side.BUY and bar.state is MarketState.LIMIT_UP:
            return order, None, "LIMIT_UP"
        if order.side is Side.SELL and bar.state is MarketState.LIMIT_DOWN:
            return order, None, "LIMIT_DOWN"
        if order.order_type is SimOrderType.LIMIT:
            assert order.limit_price is not None
            touched = bar.low <= order.limit_price if order.side is Side.BUY else bar.high >= order.limit_price
            if not touched:
                return order, None, "LIMIT_NOT_TOUCHED"
        reference = bar.open
        slipped = reference * (Decimal(1) + cost_rule.slippage_rate if order.side is Side.BUY else Decimal(1) - cost_rule.slippage_rate)
        units = (slipped / market_rule.tick_size).to_integral_value(rounding=ROUND_CEILING if order.side is Side.BUY else ROUND_FLOOR)
        price = units * market_rule.tick_size
        if order.order_type is SimOrderType.LIMIT:
            assert order.limit_price is not None
            price = min(price, order.limit_price) if order.side is Side.BUY else max(price, order.limit_price)
        capacity = int(Decimal(bar.volume) * max_participation)
        capacity = capacity // market_rule.lot_size * market_rule.lot_size
        quantity = min(order.remaining, capacity)
        quantity = quantity // market_rule.lot_size * market_rule.lot_size
        if order.side is Side.SELL:
            quantity = min(quantity, sellable_quantity // market_rule.lot_size * market_rule.lot_size)
        gross = price * quantity
        commission = max(cost_rule.minimum_commission, gross * cost_rule.commission_rate) if quantity else Decimal()
        tax = gross * cost_rule.sell_tax_rate if order.side is Side.SELL else Decimal()
        platform_fee = gross * cost_rule.platform_fee_rate
        if order.side is Side.BUY and gross + commission + platform_fee > available_cash:
            affordable = int((available_cash - cost_rule.minimum_commission) / (price * (Decimal(1) + cost_rule.commission_rate + cost_rule.platform_fee_rate)))
            quantity = max(0, affordable // market_rule.lot_size * market_rule.lot_size)
            gross = price * quantity
            commission = max(cost_rule.minimum_commission, gross * cost_rule.commission_rate) if quantity else Decimal()
            platform_fee = gross * cost_rule.platform_fee_rate
        if quantity <= 0:
            return order, None, "NO_CAPACITY_OR_BALANCE"
        slippage_cost = abs(price - reference) * quantity
        fill = SimFill(order.run_id, order.order_id, order.instrument_id, order.side, quantity, price, gross, commission, tax, platform_fee, slippage_cost, bar.market_time, bar.bar_id)
        filled_quantity = order.filled_quantity + quantity
        status = SimOrderStatus.FILLED if filled_quantity == order.quantity else SimOrderStatus.PARTIALLY_FILLED
        return replace(order, filled_quantity=filled_quantity, status=status), fill, None
