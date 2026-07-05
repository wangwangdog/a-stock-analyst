#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : 2020/9/16 20:19
# @Author : wlb
# @File   : stock_order_builder.py
# @desc   :
from panda_backtest.backtest_common.constant.string_constant import FUND_ORDER_FAILED_MESSAGE, STOCK_GEM_QUANTITY_NOT_RIGHT, \
STOCK_QUANTITY_NOT_RIGHT, FUND_PURCHASE_QUANTITY_NOT_RIGHT, FUND_REDEEM_QUANTITY_NOT_RIGHT, FUND_HAD_NO_INFO
from panda_backtest.backtest_common.data.stock.stock_info_map import StockInfoMap
from panda_backtest.backtest_common.model.result.order import Order, ACTIVE, OPEN, SIDE_BUY, LIMIT, MARKET, CLOSE, REJECTED
from panda_backtest.backtest_common.order.common.order_quotation_verify import OrderQuotationVerify
from panda_backtest.backtest_common.system.context.core_context import CoreContext
from panda_backtest.util.log.remote_log_factory import RemoteLogFactory
class FundOrderBuilder(object):

    def __init__(self, fund_info_map):
        self.context = CoreContext.get_instance()
        self.order_count = 0
        self.fund_info_map = fund_info_map
        self.order_quotation_verify = OrderQuotationVerify()

    def init_fund_order(self, account, order_dict):
        strategy_context = self.context.strategy_context
        run_info = strategy_context.run_info
        self.order_count += 1
        order_result = Order()
        order_result.order_type = 2
        order_result.account = account
        order_result.status = ACTIVE
        order_result.order_id = str(self.order_count)
        order_result.client_id = run_info.run_id
        order_result.order_book_id = order_dict['symbol']
        order_result.fund_cover_old = order_dict['fund_cover_old']
        order_result.client_id = order_dict.get('client_id', run_info.run_id)
        order_result.risk_control_id = order_dict.get('risk_control_id', None)
        order_result.remark = order_dict.get('remark', None)
        order_result.now_system_order = order_dict.get('now_system_order', 1)
        order_result.datetime = strategy_context.trade_time
        order_result.side = order_dict['side']

        if order_result.side == SIDE_BUY:
            order_result.purchase_amount = order_dict['purchase_amount']
            order_result.effect = OPEN

            if order_result.purchase_amount <= 0:
                if order_result.side == SIDE_BUY:
                    order_side = '买入'
                    order_effect = '开仓'
                else:
                    order_side = '卖出'
                    order_effect = '平仓'

                sr_logger = RemoteLogFactory.get_sr_logger()
                sr_logger.error(FUND_ORDER_FAILED_MESSAGE % (order_result.order_book_id, str(order_result.quantity),
                              