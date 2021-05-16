from decimal import Decimal
from typing import NamedTuple

from pancaketrade.network import Network
from pancaketrade.utils.config import Config
from pancaketrade.utils.generic import check_chat_id
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
)


class CreateOrderResponses(NamedTuple):
    TYPE: int = 0
    TRAILING: int = 1
    PRICE: int = 2
    AMOUNT: int = 3
    SLIPPAGE: int = 4
    GAS: int = 5


class CreateOrderConversation:
    def __init__(self, parent, config: Config):
        self.parent = parent
        self.net: Network = parent.net
        self.config = config
        self.next = CreateOrderResponses()
        self.handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.command_createorder, pattern='^create_order:0x[a-fA-F0-9]{40}$')],
            states={
                self.next.TYPE: [CallbackQueryHandler(self.command_createorder_type, pattern='^[^:]*$')],
                self.next.TRAILING: [
                    CallbackQueryHandler(self.command_createorder_trailing, pattern='^[^:]*$'),
                    MessageHandler(Filters.text & ~Filters.command, self.command_createorder_trailing),
                ],
                self.next.PRICE: [
                    CallbackQueryHandler(self.command_createorder_price, pattern='^[^:]*$'),
                    MessageHandler(Filters.text & ~Filters.command, self.command_createorder_price),
                ],
                self.next.AMOUNT: [
                    CallbackQueryHandler(self.command_createorder_amount, pattern='^[^:]*$'),
                    MessageHandler(Filters.text & ~Filters.command, self.command_createorder_amount),
                ],
                self.next.SLIPPAGE: [
                    CallbackQueryHandler(self.command_createorder_slippage, pattern='^[^:]*$'),
                    MessageHandler(Filters.text & ~Filters.command, self.command_createorder_slippage),
                ],
                self.next.GAS: [
                    CallbackQueryHandler(self.command_createorder_gas, pattern='^[^:]*$'),
                    MessageHandler(Filters.text & ~Filters.command, self.command_createorder_gas),
                ],
            },
            fallbacks=[CommandHandler('cancelorder', self.command_cancelorder)],
            name='createorder_conversation',
            persistent=False,
            conversation_timeout=120,
        )

    @check_chat_id
    def command_createorder(self, update: Update, context: CallbackContext):
        assert update.callback_query and update.effective_chat and context.user_data is not None
        query = update.callback_query
        query.answer()
        assert query.data
        token_address = query.data.split(':')[1]
        token = self.parent.watchers[token_address]
        context.user_data['createorder'] = {'token_address': token_address}
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton('Stop loss sell', callback_data='stop_loss'),
                    InlineKeyboardButton('Take profit sell', callback_data='limit_sell'),
                ],
                [
                    InlineKeyboardButton('Limit buy', callback_data='limit_buy'),
                    InlineKeyboardButton('❌ Cancel', callback_data='cancel'),
                ],
            ]
        )
        context.dispatcher.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'Creating order for token {token.name}.\nWhich type of order would you like to create?',
            reply_markup=reply_markup,
        )
        return self.next.TYPE

    @check_chat_id
    def command_createorder_type(self, update: Update, context: CallbackContext):
        assert update.callback_query and context.user_data is not None
        query = update.callback_query
        query.answer()
        if query.data == 'cancel':
            del context.user_data['createorder']
            query.edit_message_text('⚠️ OK, I\'m cancelling this command.')
            return ConversationHandler.END
        order = context.user_data['createorder']
        if query.data == 'stop_loss':
            order['type'] = 'sell'
            order['above'] = False  # below
            order['trailing_stop'] = None
            # we don't use trailing stop loss here
            query.edit_message_text('OK, the order will sell when price is below target price.')
            return self.next.AMOUNT
        elif query.data == 'limit_sell':
            order['type'] = 'sell'
            order['above'] = True  # above
        elif query.data == 'limit_buy':
            order['type'] = 'buy'
            order['above'] = False  # below
        else:
            del context.user_data['createorder']
            query.edit_message_text('⛔ That type of order is not supported.')
            return ConversationHandler.END
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton('1%', callback_data='1'),
                    InlineKeyboardButton('2%', callback_data='2'),
                    InlineKeyboardButton('5%', callback_data='5'),
                    InlineKeyboardButton('10%', callback_data='10'),
                ],
                [
                    InlineKeyboardButton('No trailing stop loss', callback_data='None'),
                    InlineKeyboardButton('❌ Cancel', callback_data='cancel'),
                ],
            ]
        )
        query.edit_message_text(
            f'OK, the order will {order["type"]} when price is '
            + f'{"above" if order["above"] else "below"} target price.\n'
            + 'Do you want to enable trailing stop loss? If yes, what is the callback rate?\n'
            + 'You can also message me a custom value in percent.',
            reply_markup=reply_markup,
        )
        return self.next.TRAILING

    @check_chat_id
    def command_createorder_trailing(self, update: Update, context: CallbackContext):
        assert update.effective_chat and context.user_data is not None
        order = context.user_data['createorder']
        token = self.parent.watchers[order['token_address']]
        current_price = self.net.get_token_price(
            token_address=token.address, token_decimals=token.decimals, sell=order['type'] == 'sell'
        )
        if update.message is None:
            assert update.callback_query
            query = update.callback_query
            query.answer()
            assert query.data
            if query.data == 'cancel':
                del context.user_data['createorder']
                query.edit_message_text('⚠️ OK, I\'m cancelling this command.')
                return ConversationHandler.END
            if query.data == 'None':
                order['trailing_stop'] = None
                query.edit_message_text(
                    'OK, the order will use no trailing stop loss.\n'
                    + f'Next, please indicate the price in <b>BNB per {token.symbol}</b> '
                    + 'at which the order will activate.\n'
                    + 'You can use scientific notation like <code>1.3E-4</code> if you want.\n'
                    + f'Current price: <b>{current_price:.6g}</b> BNB per {token.symbol}.',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Cancel', callback_data='cancel')]]),
                )
                return self.next.PRICE
            try:
                callback_rate = int(query.data)
            except ValueError:
                del context.user_data['createorder']
                query.edit_message_text('⛔ The callback rate is not recognized.')
                return ConversationHandler.END
        else:
            assert update.message and update.message.text
            try:
                callback_rate = int(update.message.text.strip())
            except ValueError:
                del context.user_data['createorder']
                update.message.reply_html('⛔ The callback rate is not recognized.')
                return ConversationHandler.END
        order['trailing_stop'] = callback_rate
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'OK, the order will use trailing stop loss with {callback_rate}% callback.\n'
            + f'Next, please indicate the price in <b>BNB per {token.symbol}</b> at which the order will activate.\n'
            + 'You can use scientific notation like <code>1.3E-4</code> if you want.\n'
            + f'Current price: <b>{current_price:.6g}</b> BNB per {token.symbol}.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Cancel', callback_data='cancel')]]),
        )
        return self.next.PRICE

    @check_chat_id
    def command_createorder_price(self, update: Update, context: CallbackContext):
        assert update.effective_chat and context.user_data is not None
        order = context.user_data['createorder']
        if update.message is None:  # we got a cancel callback
            assert update.callback_query
            query = update.callback_query
            query.answer()
            del context.user_data['createorder']
            context.bot.send_message(chat_id=update.effective_chat.id, text='⚠️ OK, I\'m cancelling this command.')
            return ConversationHandler.END
        assert update.message and update.message.text
        try:
            price = Decimal(update.message.text.strip())
        except Exception:
            update.message.reply_html('⚠️ The price you inserted is not valid. Try again:')
            return self.next.PRICE
        token = self.parent.watchers[order['token_address']]
        order['limit_price'] = str(price)
        unit = 'BNB' if order['type'] == 'buy' else token.symbol
        balance = (
            self.net.get_bnb_balance()
            if order['type'] == 'buy'
            else self.net.get_token_balance(token_address=token.address)
        )
        # if selling tokens, add options 25/50/75/100% with buttons
        reply_markup = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton('25%', callback_data='0.25'),
                        InlineKeyboardButton('50%', callback_data='0.5'),
                        InlineKeyboardButton('75%', callback_data='0.75'),
                        InlineKeyboardButton('100%', callback_data='1.0'),
                    ],
                    [
                        InlineKeyboardButton('❌ Cancel', callback_data='cancel'),
                    ],
                ]
            )
            if order['type'] == 'sell'
            else InlineKeyboardMarkup([[InlineKeyboardButton('❌ Cancel', callback_data='cancel')]])
        )
        update.message.reply_html(
            f'OK, I will {order["type"]} when the price of {token.symbol} reaches {price:.6g} BNB per token.\n'
            + f'Next, how much {unit} do you want me to use for {order["type"]}ing?\n'
            + 'You can use scientific notation like <code>1.3E-4</code> if you want.\n'
            + f'Current balance: <b>{balance:.6g} {unit}</b>',
            reply_markup=reply_markup,
        )
        return self.next.AMOUNT

    @check_chat_id
    def command_createorder_amount(self, update: Update, context: CallbackContext):
        assert update.effective_chat and context.user_data is not None
        order = context.user_data['createorder']
        token = self.parent.watchers[order['token_address']]
        if update.message is None:  # we got a button callback, either cancel or fraction of balance
            assert update.callback_query
            query = update.callback_query
            query.answer()
            if query.data == 'cancel':
                del context.user_data['createorder']
                query.edit_message_text('⚠️ OK, I\'m cancelling this command.')
                return ConversationHandler.END
            assert query.data is not None
            try:
                balance_fraction = Decimal(query.data)
            except Exception:
                del context.user_data['createorder']
                query.edit_message_text(text='⛔ The callback rate is not recognized.')
                return ConversationHandler.END
            balance = self.net.get_token_balance(token_address=token.address)
            amount = balance_fraction * balance
        else:
            assert update.message and update.message.text
            try:
                amount = Decimal(update.message.text.strip())
            except Exception:
                update.message.reply_html('⚠️ The amount you inserted is not valid. Try again:')
                return self.next.AMOUNT
        decimals = 18 if order['type'] == 'buy' else token.decimals
        unit = f'BNB worth of {token.symbol}' if order['type'] == 'buy' else token.symbol
        order['amount'] = str(int(amount * Decimal(10 ** decimals)))
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        f'{token.default_slippage}% (default)', callback_data=str(token.default_slippage)
                    ),
                    InlineKeyboardButton('1%', callback_data='1'),
                    InlineKeyboardButton('2%', callback_data='2'),
                    InlineKeyboardButton('5%', callback_data='5'),
                ],
                [
                    InlineKeyboardButton('10%', callback_data='10'),
                    InlineKeyboardButton('12%', callback_data='12'),
                    InlineKeyboardButton('15%', callback_data='15'),
                    InlineKeyboardButton('20%', callback_data='20'),
                ],
                [
                    InlineKeyboardButton('❌ Cancel', callback_data='cancel'),
                ],
            ]
        )

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'OK, I will {order["type"]} {amount:.6g} {unit} when the condition is reached.\n'
            + 'Next, please indicate the slippage in percent you want to use for this order.\n'
            + 'You can also message me a custom value in percent.',
            reply_markup=reply_markup,
        )
        return self.next.SLIPPAGE

    @check_chat_id
    def command_createorder_slippage(self, update: Update, context: CallbackContext):
        assert update.effective_chat and context.user_data is not None
        order = context.user_data['createorder']
        if update.message is None:
            assert update.callback_query
            query = update.callback_query
            query.answer()
            assert query.data
            if query.data == 'cancel':
                del context.user_data['createorder']
                query.edit_message_text('⚠️ OK, I\'m cancelling this command.')
                return ConversationHandler.END
            try:
                slippage_percent = int(query.data)
            except ValueError:
                del context.user_data['createorder']
                query.edit_message_text('⛔ The slippage is not recognized.')
                return ConversationHandler.END
        else:
            assert update.message and update.message.text
            try:
                slippage_percent = int(update.message.text.strip())
            except ValueError:
                del context.user_data['createorder']
                update.message.reply_html('⛔ The slippage is not recognized.')
                return ConversationHandler.END
        order['slippage'] = slippage_percent
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'OK, the order will use slippage of {slippage_percent}%.\n'
            + 'Finally, please indicate the gas price in GWEI for this order.\n'
            + 'Choose "Default" to use the default network price at the moment of the transaction '
            + 'or message me the value.',
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton('Default', callback_data='None'),
                        InlineKeyboardButton('❌ Cancel', callback_data='cancel'),
                    ]
                ]
            ),
        )
        return self.next.GAS

    @check_chat_id
    def command_createorder_gas(self, update: Update, context: CallbackContext):
        pass

    @check_chat_id
    def command_cancelorder(self, update: Update, context: CallbackContext):
        assert update.effective_chat and context.user_data is not None
        del context.user_data['createorder']
        context.bot.send_message(chat_id=update.effective_chat.id, text='⚠️ OK, I\'m cancelling this command.')
        return ConversationHandler.END
